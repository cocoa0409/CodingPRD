"""State-machine depth: re-entrant cycles, parallel dimensions, cascades and cross-entity gates."""

from test_helpers import (
    AUDIT_MANAGER_ID,
    TAX_SUPERVISOR_ID,
    ApiErrorId,
    assert_assessment_money,
    assert_balance_matches_ledger,
    assert_bond_instrument,
    assert_bond_position,
    assert_case_dimensions,
    assert_cents,
    assert_claim_hold,
    assert_claim_money,
    assert_gallons,
    assert_ledger_sequence,
    assert_nulls,
    assert_return_money,
    assert_return_statuses,
    assert_total_count,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import bond_payload, refund_claim_payload


class TestSuspensionCycleBondRequirement:
    def test_the_same_active_label_is_re_entered_with_a_different_bond_requirement(
        self, api, world, officer_headers
    ):
        """ACTIVE -> SUSPENDED -> ACTIVE doubles then restores the requirement, gated financially.

        PRD: "That average is then multiplied by three months of coverage, by a multiplier keyed on
        `license_type` — 1.0 for `SUPPLIER`, `DISTRIBUTOR` and `BLENDER`, 0.5 for `TRANSPORTER`,
        0.25 for `RETAILER` — and by a suspension multiplier of 2.0 while the licensee's `status` is
        `SUSPENDED` and 1.0 otherwise."
        PRD: "Suspension is the mirror image. `status` becomes `SUSPENDED`, `required_bond_cents` is
        recomputed with the suspension multiplier at 2.0 and `bond_deficiency_cents` re-derived from
        it, and *only if* that re-derived deficiency is greater than zero, every refund claim of the
        licensee whose `status` is `SUBMITTED` or `REVIEWED` has its current status copied into
        `status_before_hold`, its `status` set to `HELD` and its `hold_reason` set to
        `BOND_DEFICIENCY`."
        PRD: "Second, a licensee whose `bond_deficiency_cents` is greater than zero may not be
        reinstated; that attempt fails with `ERR_BOND_DEFICIENCY_BLOCKS_ACTIVATION` (HTTP 422)."
        PRD: "The deficiency for a licensee coming back from `SUSPENDED` is evaluated with the
        suspension multiplier of 2.0 **still in force**, which is precisely what makes the return
        leg non-trivial: a suspended licensee must post the doubled bond before it can be
        reinstated."
        PRD: "On a successful reinstatement, `status` becomes `ACTIVE`, the bond figures are
        recomputed with the suspension multiplier back at 1.0 (exactly compensating the doubling
        that suspension applied), and every refund claim of that licensee sitting in `HELD` with
        `hold_reason` of `BOND_DEFICIENCY` is returned to whatever `status_before_hold` recorded,
        with `status_before_hold` and `hold_reason` both cleared back to null."
        PRD: "Any *older* instrument of the same licensee that was still `ACTIVE` is moved to
        `RELEASED` with `release_reason` set to `SUPERSEDED_BY_NEW_BOND`, so that after the post the
        licensee's `posted_bond_cents` is exactly the new instrument's `amount_cents` and nothing
        more."

        Design: Difficulty/non_linear_state_machine/licensee_suspend_reactivate_cycle_doubles_then_restores_bond_requirement
        """
        supplier = world.new_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        first_bond = world.post_bond(supplier["id"], 1600000)
        activated = world.activate(supplier["id"])
        assert activated["status"] == "ACTIVE"
        assert_bond_position(activated, 1500000, 1600000, 0, 500000)

        suspended = world.suspend(supplier["id"], "Unreported gallons referral pending")
        assert suspended["status"] == "SUSPENDED"
        assert_bond_position(suspended, 3000000, 1600000, 1400000, 500000)

        validate_error(
            api.activate_licensee(supplier["id"], officer_headers),
            ApiErrorId.BOND_DEFICIENCY_BLOCKS_ACTIVATION,
            expected_status=422,
        )
        still_suspended = validate_success(api.get_licensee(supplier["id"], officer_headers))
        assert still_suspended["status"] == "SUSPENDED", "the refused edge changed nothing"

        second_bond = validate_success(
            api.post_bond(
                supplier["id"],
                bond_payload(3000000, suspended["version"], effective_date="2026-07-15"),
                officer_headers,
            ),
            expected_status=201,
        )
        bonds, meta = validate_paginated(api.list_bonds(supplier["id"], officer_headers))
        assert_total_count(meta, 2)
        by_id = {bond["id"]: bond for bond in bonds}
        assert_bond_instrument(
            by_id[first_bond["id"]], "RELEASED", "SUPERSEDED_BY_NEW_BOND", 1600000
        )
        assert_bond_instrument(by_id[second_bond["id"]], "ACTIVE", None, 3000000)

        covered = validate_success(api.get_licensee(supplier["id"], officer_headers))
        assert covered["status"] == "SUSPENDED", "posting collateral does not reinstate"
        assert_bond_position(covered, 3000000, 3000000, 0, 500000)

        reactivated = world.activate(supplier["id"])
        assert reactivated["status"] == "ACTIVE"
        assert_bond_position(reactivated, 1500000, 3000000, 0, 500000)
        assert (
            reactivated["dyed_violation_count"] == 0
        ), "no dyed violation ever stood in the way of the reinstatement"
        assert_cents(reactivated["balance_cents"], 0, "balance_cents")
        assert world.ledger(supplier["id"]) == [], "bond movements post no ledger entry"


class TestAuditCaseParallelDimensions:
    def test_the_case_dimension_cycles_while_the_assessment_dimension_walks_on_its_own(
        self, api, world, manager_headers, supervisor_headers
    ):
        """response_rounds cycles the case back into fieldwork while the assessment walks to FINAL.

        PRD: "An `AuditManager` drives the case dimension by supplying a `to_status`: `OPEN` to
        `FIELDWORK`, `FIELDWORK` to `PRELIM_FINDINGS`, `PRELIM_FINDINGS` to `TAXPAYER_RESPONSE`,
        `TAXPAYER_RESPONSE` back to `FIELDWORK` for another round, and `PRELIM_FINDINGS` to
        `CLOSED`."
        PRD: "The cycle back into fieldwork is bounded: `response_rounds` must be below 2 before the
        case may re-enter `FIELDWORK` from `TAXPAYER_RESPONSE`, and each traversal of that edge
        increments it, so a third attempt fails with `ERR_AUDIT_ROUND_LIMIT` (HTTP 422)."
        PRD: "Closing the case is the one and only place the two dimensions are coupled:
        `assessment_status` must be `NONE`, `FINAL` or `ABATED`. An assessment still sitting at
        `ISSUED` or `PROTESTED` must be finalized or abated before the case can close, and a
        premature closure is refused with `ERR_ASSESSMENT_PENDING_DISPOSITION` (HTTP 409)."
        PRD: "`assessment_penalty_cents` is `additional_tax_cents` multiplied by 0.50 when
        `evasion_indicator` is true and by 0.10 when it is false, rounded half up."
        PRD: "Interest runs from the original statutory due date of the audited span's last period —
        the 20th day of the month following `period_end_month`, at 23:59:59Z — to the logical clock
        at issuance: the elapsed time is divided into whole days and truncated **down**, with a
        floor of zero days if the clock has not yet passed that date, and
        `assessment_interest_cents` is `additional_tax_cents` multiplied by the daily interest rate
        of 0.00025 and by that number of days, rounded half up."
        PRD: "A `TaxSupervisor` finalizes from `ISSUED` or `PROTESTED`, setting `assessment_status`
        to `FINAL` and again leaving the ledger unchanged — the liability was already posted;
        finalization only makes it collectible."
        PRD: "Closure decrements the subject's `open_audit_count`, and when that count reaches zero,
        every refund claim of that licensee at `HELD` with `hold_reason` `OPEN_AUDIT` reverts to its
        `status_before_hold`."

        Design: Difficulty/non_linear_state_machine/audit_case_parallel_dimensions_with_response_round_cycle
        """
        subject = world.active_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )
        world.set_clock("2026-11-19T23:59:59Z")
        case = world.audit_case(
            subject["id"], "2026-08", "2026-08", selection_method="ROADSIDE_REFERRAL"
        )
        assert_case_dimensions(case, "OPEN", "NONE")
        assert case["response_rounds"] == 0
        assert case["opened_by_user_id"] == AUDIT_MANAGER_ID

        world.advance(case["id"], "FIELDWORK")
        world.advance(case["id"], "PRELIM_FINDINGS")
        world.advance(case["id"], "TAXPAYER_RESPONSE")
        second_round = world.advance(case["id"], "FIELDWORK")
        assert_case_dimensions(second_round, "FIELDWORK", "NONE")
        assert second_round["response_rounds"] == 1, "the cycle edge incremented its own counter"

        world.advance(case["id"], "PRELIM_FINDINGS")
        issued = world.issue_assessment(case["id"], 250000, False, as_headers=supervisor_headers)
        assert_case_dimensions(issued, "PRELIM_FINDINGS", "ISSUED")
        assert_assessment_money(issued, 250000, 25000, 3750, 278750)
        assert issued["assessed_by_user_id"] == TAX_SUPERVISOR_ID

        validate_error(
            api.advance_case(case["id"], "CLOSED", manager_headers),
            ApiErrorId.ASSESSMENT_PENDING_DISPOSITION,
            expected_status=409,
        )
        blocked = validate_success(api.get_audit_case(case["id"], manager_headers))
        assert_case_dimensions(blocked, "PRELIM_FINDINGS", "ISSUED")

        finalized = world.finalize(case["id"], as_headers=supervisor_headers)
        assert_case_dimensions(finalized, "PRELIM_FINDINGS", "FINAL")
        entries = world.ledger(subject["id"])
        assert_ledger_sequence(entries, [("ASSESSMENT", 278750)])

        closed = world.advance(case["id"], "CLOSED")
        assert_case_dimensions(closed, "CLOSED", "FINAL")

        licensee = validate_success(api.get_licensee(subject["id"], world.officer))
        assert licensee["open_audit_count"] == 0, "closure decremented the open count"
        assert_cents(licensee["balance_cents"], 278750, "balance_cents")
        assert_balance_matches_ledger(licensee, world.ledger(subject["id"]))


class TestDyedViolationCascade:
    def test_a_second_positive_dye_test_reaches_all_the_way_to_a_refund_hold(
        self, api, world, examiner_headers, officer_headers
    ):
        """Inspection -> penalty -> suspension -> bond deficiency -> refund hold, four hops deep.

        PRD: "First the system freezes `prior_positive_count`, the number of this licensee's earlier
        inspections with a `POSITIVE` result whose `status` is not `DISMISSED`, counted over rows
        ordered by `inspection_date` ascending and then `created_at` ascending and taking only rows
        strictly before this one."
        PRD: "A base amount is taken as the **greater** of a flat 100000 cents and `gallons_in_tank`
        multiplied by 1000 cents per gallon rounded half up. A multiplier is selected from the frozen
        count: 1.0 when it is 0, 2.0 when it is exactly 1, and 3.0 for two or more."
        PRD: "Hop one is the assessment itself: `prior_positive_count` and `penalty_cents` are
        frozen, `status` becomes `PENALTY_ASSESSED`, a `PENALTY` ledger entry for the positive
        `penalty_cents` is appended naming the inspection as its source, the licensee's
        `balance_cents` is re-derived, and the licensee's `dyed_violation_count` increases by one."
        PRD: "Hop two fires only if that new count reaches the suspension threshold of 2 **and** the
        licensee's `status` is `ACTIVE`: the licensee is driven to `SUSPENDED`."
        PRD: "Hop three follows from the suspension: `required_bond_cents` is re-derived with the 2.0
        suspension multiplier of §2.7, and `bond_deficiency_cents` with it."
        PRD: "Hop four follows from the deficiency: if `bond_deficiency_cents` is now greater than
        zero, the licensee's `SUBMITTED` and `REVIEWED` refund claims move to `HELD` with
        `hold_reason` `BOND_DEFICIENCY` and their prior status preserved in `status_before_hold`."

        Design: Difficulty/transitive_cascade/second_dyed_positive_cascades_penalty_to_suspension_to_bond_to_refund_hold
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        distributor = world.new_licensee(
            "DISTRIBUTOR", legal_name="Halvorsen Bulk Fuel Co", fein="41-3000001"
        )
        world.post_bond(distributor["id"], 1600000)
        world.activate(distributor["id"])
        world.set_clock("2026-09-05T00:00:00Z")

        built = world.build_return(
            distributor["id"],
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
                            "bill_of_lading_number": "BOL-DYE-GAS-001",
                        }
                    ],
                },
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "UNDYED_DIESEL",
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 2000.00,
                            "date": "2026-08-09",
                            "bill_of_lading_number": "BOL-DYE-UND-001",
                        }
                    ],
                },
            ],
            file=True,
        )
        assert_return_statuses(built.row, "FILED")
        assert_return_money(built.row, 17482.52, 500000, 0, 0, 500000, 0)

        before = world.bond_status(distributor["id"])
        assert_bond_position(before, 1500000, 1600000, 0)

        claim = world.refund_claim(distributor["id"], "2026-08", 1000.00)
        assert claim["status"] == "SUBMITTED"
        assert_claim_money(claim, 1000.00, 30900)

        first = world.inspection(
            distributor["id"],
            "POSITIVE",
            150.00,
            "2026-09-02",
            vehicle_identifier="MN-PLATE-8841",
        )
        assert first["prior_positive_count"] == 0
        assert first["status"] == "PENALTY_ASSESSED"
        assert_cents(first["penalty_cents"], 150000, "penalty_cents")
        after_first = validate_success(api.get_licensee(distributor["id"], officer_headers))
        assert after_first["dyed_violation_count"] == 1
        assert after_first["status"] == "ACTIVE", "one positive test is not yet a suspension"

        second = world.inspection(
            distributor["id"],
            "POSITIVE",
            150.00,
            "2026-09-04",
            vehicle_identifier="MN-PLATE-8842",
        )
        assert second["prior_positive_count"] == 1, "the count is captured before the increment"
        assert second["status"] == "PENALTY_ASSESSED"
        assert_cents(second["penalty_cents"], 300000, "penalty_cents")

        suspended = validate_success(api.get_licensee(distributor["id"], officer_headers))
        assert suspended["dyed_violation_count"] == 2
        assert suspended["status"] == "SUSPENDED", "hop two: the count reached the threshold"
        assert_bond_position(suspended, 3000000, 1600000, 1400000)

        held = validate_success(api.get_refund_claim(claim["id"], examiner_headers))
        assert_claim_hold(held, "BOND_DEFICIENCY", "SUBMITTED")
        assert_claim_money(held, 1000.00, 30900)

        entries = world.ledger(distributor["id"])
        assert_ledger_sequence(
            entries,
            [("RETURN_TAX", 500000), ("PENALTY", 150000), ("PENALTY", 300000)],
        )
        assert_cents(suspended["balance_cents"], 950000, "balance_cents")
        assert_balance_matches_ledger(suspended, entries)


class TestEscalationCascade:
    def test_escalating_one_discrepancy_opens_a_case_and_holds_an_unrelated_claim(
        self, api, world, examiner_headers, manager_headers, officer_headers
    ):
        """Resolution -> audit case -> open_audit_count -> refund hold, three hops deep.

        PRD: "`ESCALATE_TO_AUDIT` sets `status` to `ESCALATED_TO_AUDIT` and fires the same audit-case
        cascade the run's auto-escalation fires: a case is created against the escalation subject —
        the purchaser when the direction is `UNREPORTED_BY_PURCHASER`, otherwise the supplier — with
        `selection_method` `CROSS_MATCH_ESCALATION`, `selection_score` 0, this discrepancy as
        `source_discrepancy_id`, and both period bounds set to the run's period; the subject's
        `open_audit_count` increments; and because that count is now positive, the subject's
        `SUBMITTED` and `REVIEWED` refund claims move to `HELD` with `hold_reason` `OPEN_AUDIT` and
        their prior status preserved in `status_before_hold`."
        PRD: "All three branches decrease the purchaser's `open_discrepancy_count` by one and
        re-derive the purchaser's `unreported_gallons_total`, so an explained, written-off or
        escalated variance drops out of the licensee-level figure that feeds risk scoring even where
        it stays in the run-level figure."
        PRD: "And all three then check the purchaser's return: if no discrepancy naming that
        `distributor_return_id` remains in `OPEN`, `INQUIRY_SENT` or `RESPONSE_RECEIVED`, the
        return's `match_status` moves from `MATCH_VARIANCE` to `MATCH_RESOLVED`."

        Design: Difficulty/transitive_cascade/discrepancy_escalation_cascades_audit_case_to_open_count_to_refund_hold
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        distributor = world.active_licensee(
            "DISTRIBUTOR", legal_name="Halvorsen Bulk Fuel Co", fein="41-3000001"
        )
        world.set_clock("2026-09-05T00:00:00Z")

        supplier_return = world.build_return(
            supplier["id"],
            "2026-08",
            [
                {
                    "code": "SCH_5_DELIVERED_TAX_COLLECTED",
                    "product": "UNDYED_DIESEL",
                    "lines": [
                        {
                            "counterparty": distributor["id"],
                            "gallons": 9000.00,
                            "date": "2026-08-10",
                            "transaction_type": "SALE",
                            "bill_of_lading_number": "BOL-ESC-SUP-001",
                        }
                    ],
                }
            ],
            file=True,
        )
        distributor_return = world.build_return(
            distributor["id"],
            "2026-08",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "UNDYED_DIESEL",
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 2000.00,
                            "date": "2026-08-11",
                            "bill_of_lading_number": "BOL-ESC-DIS-001",
                        }
                    ],
                }
            ],
            file=True,
        )
        claim = world.refund_claim(distributor["id"], "2026-08", 1000.00)
        assert claim["status"] == "SUBMITTED"
        assert_claim_money(claim, 1000.00, 30900)

        run = world.run_cross_match("2026-08")
        finding = world.only_discrepancy(run["id"])
        assert_gallons(finding["variance_gallons"], 7000.00, "variance_gallons")
        assert finding["direction"] == "UNREPORTED_BY_PURCHASER"
        assert finding["status"] == "OPEN"

        escalated = world.resolve(finding["id"], "ESCALATE_TO_AUDIT")
        assert escalated["status"] == "ESCALATED_TO_AUDIT"

        cases, meta = validate_paginated(
            api.list_audit_cases(manager_headers, params={"source_discrepancy_id": finding["id"]})
        )
        assert_total_count(meta, 1)
        case = cases[0]
        assert case["subject_licensee_id"] == distributor["id"], "hop one: the purchaser side"
        assert case["selection_method"] == "CROSS_MATCH_ESCALATION"
        assert case["source_discrepancy_id"] == finding["id"]
        assert case["period_start_month"] == "2026-08"
        assert case["period_end_month"] == "2026-08"
        assert case["selection_score"] == 0
        assert_case_dimensions(case, "OPEN", "NONE")

        subject = validate_success(api.get_licensee(distributor["id"], officer_headers))
        assert subject["open_audit_count"] == 1, "hop two: the case bumped the open count"
        assert subject["open_discrepancy_count"] == 0, "the disposition released the discrepancy"

        held = validate_success(api.get_refund_claim(claim["id"], examiner_headers))
        assert_claim_hold(held, "OPEN_AUDIT", "SUBMITTED")
        assert_claim_money(held, 1000.00, 30900)

        purchaser_return = validate_success(
            api.get_return(distributor_return.id, examiner_headers)
        )
        assert_return_statuses(purchaser_return, "FILED", "MATCH_RESOLVED")
        seller_return = validate_success(api.get_return(supplier_return.id, examiner_headers))
        assert_return_statuses(seller_return, "FILED", "MATCH_VARIANCE")

        run_reread = validate_success(api.get_cross_match_run(run["id"], examiner_headers))
        assert run_reread["discrepancy_count"] == 1
        assert run_reread["escalated_count"] == 0, "auto-escalation never fired at 7000 gallons"
        assert run_reread["escalation_skipped_count"] == 0


class TestFilingDependsOnLicenseeState:
    def test_two_identical_drafts_diverge_only_because_one_filer_was_revoked(
        self, api, world, examiner_headers
    ):
        """The same filing request is refused or honoured purely on the filer's licence state.

        PRD: "Separately, a `REVOKED` licensee accepts no new bonds, no reinstatement, no
        suspension, no new returns, no return filing and no new refund claims; those attempts fail
        with `ERR_LICENSEE_REVOKED` (HTTP 409)."
        PRD: "The amendment fields also start at their neutral values — `amends_return_id` null,
        `amendment_sequence` 0, `amendment_count` 0 — as do `attest_name` and `filed_at`, both null
        while the return is a draft."
        PRD: "`days_late` is 0 when `filed_at` is at or before `due_at`; otherwise it is the elapsed
        time from `due_at` to `filed_at` divided into whole days and rounded **up** to the next whole
        day, so any part of a day counts as a full day."
        PRD: "The floored net is added to `taxable_gallons_total`, and the floored net multiplied by
        that product's cents-per-gallon rate, rounded half up to a whole cent **once for that
        product**, is added to `tax_due_cents`."

        Design: Difficulty/cross_entity_state_dependency/return_filing_depends_on_licensee_not_revoked
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        doomed = world.active_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )
        healthy = world.active_licensee(
            "DISTRIBUTOR", legal_name="Lakeside Petroleum Distribution LLC", fein="41-1000004"
        )
        world.set_clock("2026-09-05T00:00:00Z")

        def draft(licensee_id, bill_of_lading_number):
            return world.build_return(
                licensee_id,
                "2026-08",
                [
                    {
                        "code": "SCH_2_RECEIVED_TAX_UNPAID",
                        "product": "UNDYED_DIESEL",
                        "lines": [
                            {
                                "counterparty": supplier["id"],
                                "gallons": 100.00,
                                "date": "2026-08-12",
                                "bill_of_lading_number": bill_of_lading_number,
                            }
                        ],
                    }
                ],
            )

        doomed_draft = draft(doomed["id"], "BOL-REV-UND-001")
        healthy_draft = draft(healthy["id"], "BOL-REV-UND-002")
        assert_return_statuses(doomed_draft.row, "DRAFT", "NOT_MATCHED")
        assert_return_statuses(healthy_draft.row, "DRAFT", "NOT_MATCHED")

        world.revoke(doomed["id"], "Licence surrendered under investigation")

        validate_error(
            api.file_return(doomed_draft.id, "D. Ridgeway", examiner_headers),
            ApiErrorId.LICENSEE_REVOKED,
            expected_status=409,
        )
        still_draft = validate_success(api.get_return(doomed_draft.id, examiner_headers))
        assert_return_statuses(still_draft, "DRAFT", "NOT_MATCHED")
        assert_nulls(still_draft, ["attest_name", "filed_at"])
        revoked = validate_success(api.get_licensee(doomed["id"], world.officer))
        assert revoked["status"] == "REVOKED"
        assert_cents(revoked["balance_cents"], 0, "balance_cents")
        assert world.ledger(doomed["id"]) == [], "a refused filing posts nothing"

        filed = world.file_return(healthy_draft.id, "L. Lakeside")
        assert_return_statuses(filed, "FILED", "NOT_MATCHED")
        assert filed["attest_name"] == "L. Lakeside"
        assert_return_money(filed, 100.00, 3090, 0, 0, 3090, 0)
        good_standing = validate_success(api.get_licensee(healthy["id"], world.officer))
        assert good_standing["status"] == "ACTIVE"
        assert_cents(good_standing["balance_cents"], 3090, "balance_cents")
        assert_ledger_sequence(world.ledger(healthy["id"]), [("RETURN_TAX", 3090)])


class TestRefundCreationDependsOnAuditState:
    def test_the_identical_claim_is_refused_while_a_case_is_open_and_accepted_once_it_closes(
        self, api, world, examiner_headers, manager_headers
    ):
        """A claim's admissibility is a function of another entity's case_status, not of its own body.

        PRD: "And no audit case for that claimant may be open — any case whose `case_status` is not
        `CLOSED` freezes new claims, and the filing fails with `ERR_REFUND_BLOCKED_BY_AUDIT` (HTTP
        422)."
        PRD: "Note the division of labour between this rule and the cascade of §3.6: an open audit
        blocks claims that have not yet been filed, while claims that already existed when the case
        opened are not denied but moved to `HELD`."
        PRD: "Closure decrements the subject's `open_audit_count`, and when that count reaches zero,
        every refund claim of that licensee at `HELD` with `hold_reason` `OPEN_AUDIT` reverts to its
        `status_before_hold`."

        Design: Difficulty/cross_entity_state_dependency/refund_claim_creation_depends_on_audit_case_closed
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        claimant = world.active_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )
        world.set_clock("2026-09-05T00:00:00Z")
        world.tax_paid_pool(claimant["id"], "2026-08", 2000.00, counterparty_id=supplier["id"])

        case = world.audit_case(
            claimant["id"], "2026-08", "2026-08", selection_method="ROADSIDE_REFERRAL"
        )
        assert_case_dimensions(case, "OPEN", "NONE")
        blocked_licensee = validate_success(api.get_licensee(claimant["id"], world.officer))
        assert blocked_licensee["open_audit_count"] == 1

        payload = refund_claim_payload(claimant["id"], "2026-08", 1000.00)
        validate_error(
            api.create_refund_claim(payload, examiner_headers),
            ApiErrorId.REFUND_BLOCKED_BY_AUDIT,
            expected_status=422,
        )
        _, meta = validate_paginated(
            api.list_refund_claims(examiner_headers, params={"licensee_id": claimant["id"]})
        )
        assert_total_count(meta, 0)

        world.advance(case["id"], "FIELDWORK")
        world.advance(case["id"], "PRELIM_FINDINGS")
        closed = world.advance(case["id"], "CLOSED")
        assert_case_dimensions(closed, "CLOSED", "NONE")
        cleared = validate_success(api.get_licensee(claimant["id"], world.officer))
        assert cleared["open_audit_count"] == 0

        claim = validate_success(
            api.create_refund_claim(payload, examiner_headers), expected_status=201
        )
        assert claim["status"] == "SUBMITTED"
        assert_claim_money(claim, 1000.00, 30900)
        assert claim["hold_reason"] is None
        assert claim["status_before_hold"] is None
