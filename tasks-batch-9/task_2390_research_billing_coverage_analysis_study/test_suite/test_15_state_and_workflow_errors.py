"""The later rungs: the review guards, the money rules, publication and budget
preconditions, and the guards that a rebuild switches back on.
"""

from test_helpers import (
    ANALYST_ONE,
    COORDINATOR_ONE,
    LIAISON_TWO,
    MANAGER_ONE,
    MANAGER_TWO,
    REVIEWER_ONE,
    api_client,
    budget_build_payload,
    build_calendar_generation,
    charge_review_payload,
    consent_payload,
    create_sponsor_invoice_payload,
    create_subject_visit_payload,
    create_visit_charge_route_payload,
    build_budget,
    execute_budget,
    file_amendment,
    implement_amendment,
    item_spec,
    make_analyst_headers,
    make_coordinator_headers,
    make_liaison_headers,
    make_manager_headers,
    make_reviewer_headers,
    post_charge,
    qct_determination_payload,
    read_calendar,
    read_charge,
    read_study,
    register_subject,
    remittance_payload,
    resolve_finding_payload,
    route_spec,
    set_clock,
    setup_consented_subject,
    setup_open_to_accrual,
    setup_priced_study_with_sponsor_charges,
    setup_responded_finding,
    setup_sponsor_unbilled_charge,
    setup_study_with_approved_analysis,
    setup_submitted_invoice,
    validate_error,
    validate_paginated,
    validate_success,
    visit_spec,
)

SPONSOR_INFUSION = item_spec(
    "J9999",
    classification="RESEARCH_PAID",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=50000,
    negotiated_unit_cents=40000,
    expected_occurrences=1,
)
ROUTINE_PANEL = item_spec(
    "80053",
    classification="ROUTINE_CARE",
    budget_category="PER_PATIENT",
    medicare_coverage_basis="STANDARD_OF_CARE",
    charge_master_unit_cents=9000,
    negotiated_unit_cents=9000,
    expected_occurrences=3,
)
CONDITIONAL_ROUTINE = item_spec(
    "71046",
    classification="ROUTINE_CARE",
    budget_category="PER_PATIENT",
    medicare_coverage_basis="QCT_CONDITIONAL",
    charge_master_unit_cents=9000,
    negotiated_unit_cents=9000,
    expected_occurrences=2,
)


def _review(charge_id, decision, **overrides):
    return api_client.review_charge(
        charge_id,
        charge_review_payload(decision, **overrides),
        make_reviewer_headers(REVIEWER_ONE),
    )


class TestTheTwoCoverageLookupFailuresAreDistinct:
    """One rung apart, and two different HTTP statuses."""

    def test_01_a_charge_older_than_every_approval_has_no_effective_analysis(self):
        """The analysis was approved four days after the service date, so the
        operational candidate set is empty — while the persisted audit-view answer
        still names the sponsor.

        PRD §3.7: "Review also requires an operational-view analysis to exist for
        the charge's `service_date` — none means `ERR_NO_EFFECTIVE_ANALYSIS` — and
        requires the charge's `charge_code` to match an `item_code` on that
        analysis, failing otherwise with
        `ERR_CHARGE_CODE_NOT_IN_COVERAGE_ANALYSIS`."

        Design: Corner/errors/charge_review_without_an_analysis_effective_at_service_date_is_rejected
        """
        ctx = setup_study_with_approved_analysis(
            [SPONSOR_INFUSION],
            clock="2026-08-05T09:00:00Z",
            qct_registry_number="NCT10000165",
            study_overrides={"protocol_number": "AMC-2390-C65"},
        )
        assert ctx["analysis"]["approved_at"] == "2026-08-05T09:00:00.000Z"
        assert ctx["study"]["billing_hold_posture"] == "OPEN"

        stale = post_charge(
            ctx["study"]["id"],
            charge_code="J9999",
            service_date="2026-08-01",
            amount_cents=40000,
        )
        # The audit view ignores service_date entirely, so this was written.
        assert stale["expected_routing_target"] == "SPONSOR"

        validate_error(
            _review(stale["id"], "HOLD_FOR_SPONSOR"),
            "ERR_NO_EFFECTIVE_ANALYSIS",
            409,
        )
        untouched = read_charge(stale["id"])
        assert untouched["routing_state"] == "UNROUTED"
        assert untouched["reviewed_by_user_id"] is None
        assert untouched["reviewed_at"] is None
        assert untouched["expected_routing_target"] == "SPONSOR"

        # A charge served on the approval date itself is inside the window.
        same_day = post_charge(
            ctx["study"]["id"],
            charge_code="J9999",
            service_date="2026-08-05",
            amount_cents=40000,
        )
        held = validate_success(_review(same_day["id"], "HOLD_FOR_SPONSOR"), 200)
        assert held["routing_state"] == "ROUTED_SPONSOR"
        assert held["reviewed_by_user_id"] == REVIEWER_ONE

    def test_02_a_code_missing_from_the_effective_grid_is_the_next_rung_down(self):
        """An analysis is effective, so the failure is the item lookup and the
        status is 422 rather than 409.

        PRD §3.7: "Within whichever analysis was chosen, the server looks for items
        whose `item_code` equals the charge's `charge_code` and takes the
        oldest-created match, yielding that item's `billable_to` as the answer; if
        no analysis was found, or no item matched, the answer is `UNDETERMINED`."

        Design: Corner/errors/charge_code_absent_from_the_effective_analysis_is_rejected
        """
        ctx = setup_study_with_approved_analysis(
            [SPONSOR_INFUSION],
            qct_registry_number="NCT10000166",
            study_overrides={"protocol_number": "AMC-2390-C66"},
        )
        unknown_code = post_charge(
            ctx["study"]["id"],
            charge_code="99213",
            service_date="2026-08-01",
            amount_cents=12000,
        )
        assert unknown_code["expected_routing_target"] == "UNDETERMINED"

        validate_error(
            _review(unknown_code["id"], "HOLD_FOR_SPONSOR"),
            "ERR_CHARGE_CODE_NOT_IN_COVERAGE_ANALYSIS",
            422,
        )
        untouched = read_charge(unknown_code["id"])
        assert untouched["routing_state"] == "UNROUTED"
        assert untouched["coverage_item_id"] is None

        on_the_grid = post_charge(
            ctx["study"]["id"],
            charge_code="J9999",
            service_date="2026-08-01",
            amount_cents=40000,
        )
        held = validate_success(_review(on_the_grid["id"], "HOLD_FOR_SPONSOR"), 200)
        assert held["coverage_item_id"] == ctx["item_by_code"]["J9999"]["id"]


class TestRemittanceMoneyRulesAreCheckedFirst:
    """The equality boundary belongs to exactly one outcome."""

    def test_03_a_short_payment_equal_to_the_net_total_is_refused(self):
        """40,000 against a net of exactly 40,000 is not a short payment, and the
        invoice does not move.

        PRD §3.8: "`PAID_IN_FULL` requires `amount_paid_cents` to be either omitted
        or exactly equal to `net_total_cents`. `SHORT_PAID` requires
        `amount_paid_cents` to be at least zero and strictly less than
        `net_total_cents`. Either violation is `ERR_REMITTANCE_AMOUNT_INVALID`."

        Design: Corner/errors/short_paid_remittance_equal_to_the_net_total_is_rejected
        """
        ctx = setup_submitted_invoice(
            [{"charge_code": "J9999", "service_date": "2026-08-01", "amount_cents": 40000}],
            item_specs=[SPONSOR_INFUSION],
            indirect_rate_pct=20.0,
            qct_registry_number="NCT10000167",
            study_overrides={
                "protocol_number": "AMC-2390-C67",
                "funding_source": "INVESTIGATOR_INITIATED",
            },
        )
        invoice = ctx["invoice"]
        # An investigator-initiated study takes 0.0 percent outright.
        assert ctx["study"]["effective_indirect_rate_pct"] == 0.0
        assert invoice["subtotal_cents"] == 40000
        assert invoice["indirect_cents"] == 0
        assert invoice["gross_total_cents"] == 40000
        assert invoice["volume_credit_cents"] == 0
        assert invoice["net_total_cents"] == 40000
        assert invoice["status"] == "SUBMITTED"

        validate_error(
            api_client.record_remittance(
                invoice["id"],
                remittance_payload("SHORT_PAID", amount_paid_cents=40000),
                make_manager_headers(MANAGER_ONE),
            ),
            "ERR_REMITTANCE_AMOUNT_INVALID",
            422,
        )
        # The mirror-image violation on the other outcome.
        validate_error(
            api_client.record_remittance(
                invoice["id"],
                remittance_payload("PAID_IN_FULL", amount_paid_cents=39999),
                make_manager_headers(MANAGER_ONE),
            ),
            "ERR_REMITTANCE_AMOUNT_INVALID",
            422,
        )

        rows, meta = validate_paginated(
            api_client.list_study_sponsor_invoices(
                ctx["study"]["id"], make_manager_headers(MANAGER_ONE)
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "SUBMITTED"
        assert rows[0]["short_paid"] is False
        assert read_study(ctx["study"]["id"])["sponsor_collected_cents"] == 0

        paid = validate_success(
            api_client.record_remittance(
                invoice["id"],
                remittance_payload("PAID_IN_FULL", amount_paid_cents=40000),
                make_manager_headers(MANAGER_ONE),
            ),
            200,
        )
        assert paid["status"] == "PAID"
        assert paid["amount_paid_cents"] == 40000
        assert paid["short_paid"] is False
        settled = read_study(ctx["study"]["id"])
        assert settled["sponsor_collected_cents"] == 40000
        assert settled["sponsor_written_off_cents"] == 0


class TestAnEmptyInvoiceIsNeverPersisted:
    """The selector runs after the concurrency guard and can still yield nothing."""

    def test_04_an_invoice_whose_pool_is_empty_is_refused_and_not_created(self):
        """The only sponsor charge is dated after the cutoff, so the pool is empty;
        moving the cutoff alone turns the identical request into a 201.

        PRD §3.8: "If the walk selects nothing at all, the request fails with
        `ERR_NO_INVOICEABLE_CHARGES`; an empty invoice is never created."

        Design: Corner/errors/invoice_creation_with_no_eligible_charges_is_rejected
        """
        ctx = setup_priced_study_with_sponsor_charges(
            [{"charge_code": "J9999", "service_date": "2026-09-15", "amount_cents": 40000}],
            item_specs=[SPONSOR_INFUSION],
            indirect_rate_pct=32.0,
            qct_registry_number="NCT10000168",
            study_overrides={
                "protocol_number": "AMC-2390-C68",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        study_id = ctx["study"]["id"]
        version = ctx["study"]["version"]
        assert ctx["charges"][0]["routing_state"] == "ROUTED_SPONSOR"

        validate_error(
            api_client.create_sponsor_invoice(
                create_sponsor_invoice_payload(
                    study_id, version, period_end_date="2026-08-31"
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            "ERR_NO_INVOICEABLE_CHARGES",
            409,
        )
        _, meta = validate_paginated(
            api_client.list_study_sponsor_invoices(
                study_id, make_manager_headers(MANAGER_ONE)
            )
        )
        assert meta["total_count"] == 0
        assert read_study(study_id)["version"] == version
        assert read_charge(ctx["charges"][0]["id"])["sponsor_invoice_id"] is None

        invoice = validate_success(
            api_client.create_sponsor_invoice(
                create_sponsor_invoice_payload(
                    study_id, version, period_end_date="2026-09-30"
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            201,
        )
        assert invoice["line_count"] == 1
        assert invoice["sequence_number"] == 1
        assert invoice["invoice_number"] == "INV-AMC-2390-C68-001"
        assert invoice["subtotal_cents"] == 40000


class TestPublicationAndBudgetBasisPreconditions:
    """Both are completeness checks over the same calendar generation."""

    def test_05_publication_is_refused_while_a_per_patient_item_is_unrouted(self):
        """Both billable per-patient items must be routed somewhere; routing the
        second one and nothing else publishes the identical calendar.

        PRD §3.4: "and its `unrouted_per_patient_item_count`, the number of
        coverage items on the source analysis whose `budget_category` is
        `PER_PATIENT` and whose `billable_to` is either `PAYER` or `SPONSOR` that
        have no route at all on this calendar."

        Design: Corner/errors/publishing_with_an_unrouted_per_patient_item_is_rejected
        """
        ctx = setup_study_with_approved_analysis(
            [SPONSOR_INFUSION, ROUTINE_PANEL],
            qct_basis=None,
            study_overrides={"protocol_number": "AMC-2390-C69"},
        )
        ctx = build_calendar_generation(
            ctx,
            [visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)],
            [route_spec("Cycle 1 Day 1", "J9999")],
        )
        calendar_id = ctx["calendar"]["id"]
        assert ctx["calendar"]["status"] == "DRAFT"
        assert ctx["calendar"]["routed_item_count"] == 1
        assert ctx["calendar"]["unrouted_per_patient_item_count"] == 1

        validate_error(
            api_client.publish_study_calendar(
                calendar_id, make_reviewer_headers(REVIEWER_ONE)
            ),
            "ERR_UNROUTED_PER_PATIENT_ITEM",
            422,
        )
        blocked = read_calendar(calendar_id)
        assert blocked["status"] == "DRAFT"
        assert blocked["published_at"] is None

        validate_success(
            api_client.create_visit_charge_route(
                create_visit_charge_route_payload(
                    ctx["visit_by_name"]["Cycle 1 Day 1"]["id"],
                    ctx["item_by_code"]["80053"]["id"],
                ),
                make_analyst_headers(ANALYST_ONE),
            ),
            201,
        )
        assert read_calendar(calendar_id)["unrouted_per_patient_item_count"] == 0

        published = validate_success(
            api_client.publish_study_calendar(
                calendar_id, make_reviewer_headers(REVIEWER_ONE)
            ),
            200,
        )
        assert published["status"] == "PUBLISHED"
        assert published["published_at"] is not None

    def test_06_a_calendar_driven_basis_needs_a_published_generation(self):
        """The calendar is fully routed but still `DRAFT`, so only the
        calendar-driven basis is refused.

        PRD §3.5: "Choosing `CALENDAR_DRIVEN` additionally requires that a calendar
        built from that same source analysis be standing at `PUBLISHED`; if none
        is, the build is refused with `ERR_NO_PUBLISHED_CALENDAR_FOR_BASIS`."

        Design: Corner/errors/calendar_driven_budget_basis_without_a_published_calendar_is_rejected
        """
        ctx = setup_study_with_approved_analysis(
            [SPONSOR_INFUSION],
            qct_basis=None,
            study_overrides={
                "protocol_number": "AMC-2390-C70",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        ctx = build_calendar_generation(
            ctx,
            [visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)],
            [route_spec("Cycle 1 Day 1", "J9999")],
        )
        study_id = ctx["study"]["id"]
        version = ctx["study"]["version"]
        assert ctx["calendar"]["status"] == "DRAFT"
        assert ctx["calendar"]["unrouted_per_patient_item_count"] == 0

        validate_error(
            api_client.build_budget(
                study_id,
                budget_build_payload(
                    ctx["analysis"]["id"], version, basis="CALENDAR_DRIVEN"
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            "ERR_NO_PUBLISHED_CALENDAR_FOR_BASIS",
            422,
        )
        refused = read_study(study_id)
        assert refused["budget_status"] == "NOT_BUILT"
        assert refused["version"] == version

        built = validate_success(
            api_client.build_budget(
                study_id,
                budget_build_payload(
                    ctx["analysis"]["id"], version, basis="COVERAGE_DRIVEN"
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            200,
        )
        assert built["budget_status"] == "BUILT"
        assert built["budget_basis"] == "COVERAGE_DRIVEN"
        assert built["per_patient_subtotal_cents"] == 40000


class TestTheDowngradeBlockIsDataDependent:
    """What the approved grid contains decides whether the downgrade lands."""

    def test_07_a_declaration_is_refused_only_over_conditional_routine_items(self):
        """A sibling protocol whose approved grid carries a standard-of-care
        routine item accepts the very same declaration.

        PRD §3.1: "And a determination that would leave `qct_determination` at
        `NON_QUALIFYING` is refused with `ERR_QCT_DOWNGRADE_BLOCKED` while the
        study's `APPROVED` analysis carries at least one routine-care item whose
        Medicare basis is conditional on trial qualification — the billing office
        cannot retroactively strip the justification out from under items it has
        already blessed."

        Design: Corner/errors/non_qualifying_downgrade_with_conditional_items_is_rejected
        """
        conditional = setup_study_with_approved_analysis(
            [CONDITIONAL_ROUTINE],
            qct_registry_number="NCT10000171",
            study_overrides={"protocol_number": "AMC-2390-C71"},
        )
        assert conditional["analysis"]["qct_conditional_item_count"] == 1
        assert conditional["study"]["qct_determination"] == "DEEMED_QUALIFYING"
        version = conditional["study"]["version"]

        validate_error(
            api_client.record_qct_determination(
                conditional["study"]["id"],
                qct_determination_payload(basis="NOT_QUALIFYING_DECLARED"),
                make_reviewer_headers(REVIEWER_ONE),
            ),
            "ERR_QCT_DOWNGRADE_BLOCKED",
            409,
        )
        held = read_study(conditional["study"]["id"])
        assert held["qct_determination"] == "DEEMED_QUALIFYING"
        assert held["qct_basis"] == "DEEMED_IND_IDE"
        assert held["billing_hold_posture"] == "OPEN"
        assert held["version"] == version

        sibling = setup_study_with_approved_analysis(
            [ROUTINE_PANEL],
            qct_registry_number="NCT10000172",
            study_overrides={"protocol_number": "AMC-2390-C72"},
        )
        assert sibling["analysis"]["qct_conditional_item_count"] == 0
        downgraded = validate_success(
            api_client.record_qct_determination(
                sibling["study"]["id"],
                qct_determination_payload(basis="NOT_QUALIFYING_DECLARED"),
                make_reviewer_headers(REVIEWER_ONE),
            ),
            200,
        )
        assert downgraded["qct_determination"] == "NON_QUALIFYING"
        assert downgraded["qct_basis"] == "NOT_QUALIFYING_DECLARED"
        assert downgraded["billing_hold_posture"] == "PAYER_BLOCKED"


class TestARebuildSuspendsConsent:
    """The lifecycle never moves; the budget dimension does all the work."""

    def test_08_consent_is_blocked_until_the_rebuilt_budget_is_re_executed(self):
        """Registration still succeeds on the same protocol, which isolates the
        refusal to the budget precondition.

        PRD §3.5: "Because a rebuild drops an executed budget back to `BUILT` and
        clears the executing user, a mid-study rebuild suspends consent — the
        study's `budget_status` is no longer `EXECUTED`, so consent fails with
        `ERR_BUDGET_NOT_EXECUTED` until a second manager executes the rebuilt
        figures."

        Design: Corner/errors/consent_after_a_mid_study_budget_rebuild_is_rejected
        """
        ctx = setup_open_to_accrual(
            [SPONSOR_INFUSION],
            [visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)],
            [route_spec("Cycle 1 Day 1", "J9999")],
            qct_registry_number="NCT10000173",
            study_overrides={"protocol_number": "AMC-2390-C73"},
        )
        assert ctx["study"]["budget_status"] == "EXECUTED"

        rebuilt = build_budget(
            ctx["study"]["id"], ctx["analysis"]["id"], indirect_rate_pct=25.0
        )
        assert rebuilt["budget_status"] == "BUILT"
        assert rebuilt["budget_executed_by_user_id"] is None
        assert rebuilt["lifecycle_status"] == "OPEN_TO_ACCRUAL"

        subject = register_subject(ctx["study"]["id"], subject_number="S-001")
        assert subject["status"] == "SCREENING"

        validate_error(
            api_client.consent_study_subject(
                subject["id"],
                consent_payload(consent_date="2026-09-01"),
                make_coordinator_headers(COORDINATOR_ONE),
            ),
            "ERR_BUDGET_NOT_EXECUTED",
            409,
        )
        still_screening = validate_success(
            api_client.get_study_subject(
                subject["id"], make_coordinator_headers(COORDINATOR_ONE)
            ),
            200,
        )
        assert still_screening["status"] == "SCREENING"
        assert still_screening["consented_calendar_id"] is None

        execute_budget(ctx["study"]["id"], user_id=MANAGER_TWO)
        consented = validate_success(
            api_client.consent_study_subject(
                subject["id"],
                consent_payload(consent_date="2026-09-01"),
                make_coordinator_headers(COORDINATOR_ONE),
            ),
            200,
        )
        assert consented["status"] == "CONSENTED"
        assert consented["consented_calendar_id"] == ctx["calendar"]["id"]
        assert consented["consented_calendar_generation"] == 1


class TestARebuildRequiredCalendarBlocksScheduling:
    """The pinned generation was dragged out from under the subject."""

    def test_09_scheduling_and_re_implementation_are_both_refused(self):
        """The calendar is `REBUILD_REQUIRED` rather than stale-at-completion, and
        the amendment is `IMPLEMENTED` rather than absent.

        PRD §3.6: "the pinned calendar must still be `PUBLISHED` — one that has
        moved to `REBUILD_REQUIRED` or `RETIRED` yields
        `ERR_CALENDAR_NOT_PUBLISHED`."

        Design: Corner/errors/visit_scheduling_and_re_implementation_after_a_rebuild_are_rejected
        """
        ctx = setup_open_to_accrual(
            [SPONSOR_INFUSION],
            [visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)],
            [route_spec("Cycle 1 Day 1", "J9999")],
            qct_registry_number="NCT10000174",
            study_overrides={"protocol_number": "AMC-2390-C74"},
        )
        subject = setup_consented_subject(ctx, consent_date="2026-09-01")
        assert subject["consented_calendar_generation"] == 1

        amendment = file_amendment(
            ctx["study"]["id"],
            scope="VISIT_SCHEDULE_CHANGE",
            effective_date="2026-09-02",
        )
        assert amendment["calendar_rebuild_required"] is True
        set_clock("2026-09-02T00:00:00Z")
        implemented = implement_amendment(amendment["id"])
        assert implemented["status"] == "IMPLEMENTED"
        assert read_calendar(ctx["calendar"]["id"])["status"] == "REBUILD_REQUIRED"
        after_cascade = read_study(ctx["study"]["id"])
        assert after_cascade["lifecycle_status"] == "COVERAGE_PENDING"
        assert after_cascade["budget_status"] == "SUPERSEDED"
        assert after_cascade["rebuild_required_calendar_count"] == 1
        assert after_cascade["billing_hold_posture"] == "ALL_BLOCKED"

        validate_error(
            api_client.create_subject_visit(
                create_subject_visit_payload(
                    subject["id"],
                    ctx["visit_by_name"]["Cycle 1 Day 1"]["id"],
                    "2026-09-02",
                ),
                make_coordinator_headers(COORDINATOR_ONE),
            ),
            "ERR_CALENDAR_NOT_PUBLISHED",
            409,
        )
        _, meta = validate_paginated(
            api_client.list_subject_visits(
                make_coordinator_headers(COORDINATOR_ONE),
                params={"study_subject_id": subject["id"]},
            )
        )
        assert meta["total_count"] == 0

        validate_error(
            api_client.implement_amendment(
                amendment["id"], make_manager_headers(MANAGER_ONE)
            ),
            "ERR_AMENDMENT_NOT_SUBMITTED",
            409,
        )
        rows, amendment_meta = validate_paginated(
            api_client.list_study_amendments(
                ctx["study"]["id"], make_manager_headers(MANAGER_ONE)
            )
        )
        assert amendment_meta["total_count"] == 1
        assert rows[0]["status"] == "IMPLEMENTED"
        # The rebuild counter is not double-counted by the refused re-run.
        assert read_study(ctx["study"]["id"])["rebuild_required_calendar_count"] == 1


class TestTheRefundDispositionNeedsAPayerBilledCharge:
    """A sponsor-held charge has nothing to refund."""

    def test_10_a_refund_on_a_sponsor_routed_charge_is_refused(self):
        """No replacement row is created, the finding stays `RESPONDED`, and
        `NO_ACTION` on the very same finding closes it.

        PRD §3.9: "A `disposition` of `REFUND_AND_REROUTE` moves the finding
        `RESPONDED → CLOSED_REFUNDED` and requires the finding to name a charge
        whose `billing_state` is `BILLED_PAYER`; a finding with no `charge_id`, or
        one whose charge is in any other billing state, is refused with
        `ERR_CHARGE_NOT_BILLED_TO_PAYER`."

        Design: Corner/errors/refund_disposition_on_a_sponsor_routed_charge_is_rejected
        """
        ctx = setup_sponsor_unbilled_charge(
            qct_registry_number="NCT10000175",
            study_overrides={"protocol_number": "AMC-2390-C75"},
        )
        assert ctx["charge"]["routing_state"] == "ROUTED_SPONSOR"
        assert ctx["charge"]["billing_state"] == "UNBILLED"

        ctx = setup_responded_finding(
            ctx,
            charge_id=ctx["charge"]["id"],
            finding_type="IMPROPER_PAYER_BILL",
            claimed_amount_cents=40000,
        )
        assert ctx["finding"]["status"] == "RESPONDED"
        assert ctx["finding"]["charge_id"] == ctx["charge"]["id"]
        finding_version = ctx["finding"]["version"]

        validate_error(
            api_client.resolve_audit_finding(
                ctx["finding"]["id"],
                resolve_finding_payload("REFUND_AND_REROUTE"),
                make_liaison_headers(LIAISON_TWO),
            ),
            "ERR_CHARGE_NOT_BILLED_TO_PAYER",
            409,
        )
        unchanged = read_charge(ctx["charge"]["id"])
        assert unchanged["billing_state"] == "UNBILLED"
        assert unchanged["routing_state"] == "ROUTED_SPONSOR"
        # No REFUND_REPLACEMENT row was created.
        rows, meta = validate_paginated(
            api_client.list_charges(
                make_manager_headers(MANAGER_ONE),
                params={"study_id": ctx["study"]["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == ctx["charge"]["id"]

        still_responded = validate_success(
            api_client.get_audit_finding(
                ctx["finding"]["id"], make_liaison_headers(LIAISON_TWO)
            ),
            200,
        )
        assert still_responded["status"] == "RESPONDED"
        assert still_responded["refund_amount_cents"] == 0
        assert still_responded["version"] == finding_version
        blocked_study = read_study(ctx["study"]["id"])
        assert blocked_study["open_finding_count"] == 1
        assert blocked_study["payer_refunded_cents"] == 0
        assert blocked_study["billing_hold_posture"] == "ALL_BLOCKED"

        closed = validate_success(
            api_client.resolve_audit_finding(
                ctx["finding"]["id"],
                resolve_finding_payload("NO_ACTION"),
                make_liaison_headers(LIAISON_TWO),
            ),
            200,
        )
        assert closed["status"] == "CLOSED_NO_ACTION"
        assert closed["refund_amount_cents"] == 0
        reopened = read_study(ctx["study"]["id"])
        assert reopened["open_finding_count"] == 0
        assert reopened["billing_hold_posture"] == "OPEN"


class TestTheSubjectIsPinnedToOneGeneration:
    """A visit from another generation is a cross-reference failure, not a 404."""

    def test_11_scheduling_from_a_generation_the_subject_never_consented_to_fails(self):
        """The pinned generation is still `PUBLISHED`, so the earlier guard passes
        and the request dies on the cross-reference.

        PRD §3.6: "The named calendar visit must belong to the subject's
        `consented_calendar_id`, or the request is refused with
        `ERR_CALENDAR_VISIT_NOT_ON_CONSENTED_CALENDAR`, and the pinned calendar
        must still be `PUBLISHED` — one that has moved to `REBUILD_REQUIRED` or
        `RETIRED` yields `ERR_CALENDAR_NOT_PUBLISHED`."

        Design: Corner/errors/scheduling_a_visit_from_a_calendar_the_subject_never_consented_to_is_rejected
        """
        ctx = setup_open_to_accrual(
            [SPONSOR_INFUSION],
            [visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)],
            [route_spec("Cycle 1 Day 1", "J9999")],
            qct_registry_number="NCT10000176",
            study_overrides={"protocol_number": "AMC-2390-C76"},
        )
        pinned_calendar_id = ctx["calendar"]["id"]
        pinned_visit_id = ctx["visit_by_name"]["Cycle 1 Day 1"]["id"]
        subject = setup_consented_subject(ctx, consent_date="2026-09-01")
        assert subject["consented_calendar_id"] == pinned_calendar_id

        # A second generation, still DRAFT, carrying its own visit row.
        ctx = build_calendar_generation(
            ctx, [visit_spec("Baseline (revised)", 1, 0, 0, 5)]
        )
        foreign_visit = ctx["visit_by_name"]["Baseline (revised)"]
        assert ctx["calendar"]["id"] != pinned_calendar_id
        assert ctx["calendar"]["build_generation"] == 2
        assert ctx["calendar"]["status"] == "DRAFT"
        assert read_calendar(pinned_calendar_id)["status"] == "PUBLISHED"

        validate_error(
            api_client.create_subject_visit(
                create_subject_visit_payload(
                    subject["id"], foreign_visit["id"], "2026-09-02"
                ),
                make_coordinator_headers(COORDINATOR_ONE),
            ),
            "ERR_CALENDAR_VISIT_NOT_ON_CONSENTED_CALENDAR",
            422,
        )
        _, meta = validate_paginated(
            api_client.list_subject_visits(
                make_coordinator_headers(COORDINATOR_ONE),
                params={"study_subject_id": subject["id"]},
            )
        )
        assert meta["total_count"] == 0

        scheduled = validate_success(
            api_client.create_subject_visit(
                create_subject_visit_payload(
                    subject["id"], pinned_visit_id, "2026-09-02"
                ),
                make_coordinator_headers(COORDINATOR_ONE),
            ),
            201,
        )
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["calendar_visit_id"] == pinned_visit_id
        assert scheduled["calendar_generation_at_schedule"] == 1
        assert scheduled["day_offset_actual"] == 1
