"""State machine edges: licence lifecycle, bonds, returns, discrepancies, claims."""

from test_helpers import (
    ApiErrorId,
    assert_bond_instrument,
    assert_bond_position,
    assert_claim_money,
    assert_gallons,
    assert_ledger_row,
    assert_nulls,
    assert_return_money,
    assert_return_statuses,
    assert_total_count,
    ids_of,
    refund_cents_for,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import bond_payload, refund_claim_payload, resolve_payload
from test_helpers.test_users import RETURNS_EXAMINER_ID


class TestLicenceLifecycle:
    def test_a_fully_bonded_pending_licensee_activates(self, api, world, officer_headers):
        """The PENDING_BOND -> ACTIVE leg passes once posted bond has reached the requirement.

        PRD: "`PENDING_BOND → ACTIVE` and `SUSPENDED → ACTIVE` are both reinstatement legs driven
        by a `LicensingOfficer`; `ACTIVE → SUSPENDED` is a suspension leg driven by a
        `LicensingOfficer` or a `TaxSupervisor` and requires a `reason`; and
        `PENDING_BOND → REVOKED`, `ACTIVE → REVOKED` and `SUSPENDED → REVOKED` are all the same
        revocation leg, driven by a `LicensingOfficer` with a `reason`, ending in the terminal
        `REVOKED` state."
        PRD: "On a successful reinstatement, `status` becomes `ACTIVE`, the bond figures are
        recomputed with the suspension multiplier back at 1.0 (exactly compensating the doubling
        that suspension applied), and every refund claim of that licensee sitting in `HELD` with
        `hold_reason` of `BOND_DEFICIENCY` is returned to whatever `status_before_hold` recorded,
        with `status_before_hold` and `hold_reason` both cleared back to null."

        Design: Corner/state_machines/licensee_activate_moves_pending_bond_to_active
        """
        licensee = world.new_licensee("DISTRIBUTOR", legal_name="Papa Distribution Inc")
        version_at_registration = licensee["version"]
        world.post_bond(licensee["id"], 1500000, surety_name="Granite Surety Co")

        response = api.activate_licensee(licensee["id"], officer_headers)

        activated = validate_success(response, expected_status=200)
        assert activated["status"] == "ACTIVE"
        assert_bond_position(
            activated,
            required_bond_cents=1500000,
            posted_bond_cents=1500000,
            bond_deficiency_cents=0,
        )
        assert activated["version"] > version_at_registration, (
            "the bond post and the activate each bump the licensee, so the version must have "
            f"moved past {version_at_registration}"
        )

        rows, meta = validate_paginated(
            api.list_licensees(officer_headers, params={"status": "ACTIVE"})
        )
        assert_total_count(meta, 1, "ACTIVE licensee total_count")
        assert ids_of(rows) == [licensee["id"]]

    def test_activating_under_the_requirement_is_refused_and_leaves_pending_bond(
        self, api, world, officer_headers
    ):
        """A 900000-cent bond against a 1500000-cent requirement cannot buy activation.

        PRD: "Second, a licensee whose `bond_deficiency_cents` is greater than zero may not be
        reinstated; that attempt fails with `ERR_BOND_DEFICIENCY_BLOCKS_ACTIVATION` (HTTP 422)."

        Design: Corner/state_machines/activate_while_underbonded_returns_bond_deficiency_blocks_activation
        """
        licensee = world.new_licensee("DISTRIBUTOR", legal_name="Quebec Distribution Inc")
        world.post_bond(licensee["id"], 900000, surety_name="Granite Surety Co")

        response = api.activate_licensee(licensee["id"], officer_headers)

        validate_error(
            response, ApiErrorId.BOND_DEFICIENCY_BLOCKS_ACTIVATION, expected_status=422
        )
        reread = world.licensee(licensee["id"])
        assert reread["status"] == "PENDING_BOND"
        assert_bond_position(
            reread,
            required_bond_cents=1500000,
            posted_bond_cents=900000,
            bond_deficiency_cents=600000,
        )

    def test_a_second_bond_post_supersedes_the_first_instead_of_adding_to_it(
        self, api, world, officer_headers
    ):
        """Posted collateral is the newest instrument alone, never the sum of both instruments.

        PRD: "Any *older* instrument of the same licensee that was still `ACTIVE` is moved to
        `RELEASED` with `release_reason` set to `SUPERSEDED_BY_NEW_BOND`, so that after the post
        the licensee's `posted_bond_cents` is exactly the new instrument's `amount_cents` and
        nothing more."

        Design: Corner/state_machines/new_bond_post_supersedes_the_prior_active_bond
        """
        licensee = world.new_licensee("DISTRIBUTOR", legal_name="Romeo Distribution Inc")
        first_bond = world.post_bond(
            licensee["id"], 900000, surety_name="Granite Surety Co"
        )
        current_version = world.licensee(licensee["id"])["version"]

        response = api.post_bond(
            licensee["id"],
            bond_payload(
                1500000,
                current_version,
                surety_name="Iron Range Surety Co",
                effective_date="2026-07-15",
            ),
            officer_headers,
        )

        second_bond = validate_success(response, expected_status=201)
        assert_bond_instrument(second_bond, "ACTIVE", None, amount_cents=1500000)

        active_rows, active_meta = validate_paginated(
            api.list_bonds(licensee["id"], officer_headers, params={"status": "ACTIVE"})
        )
        assert_total_count(active_meta, 1, "ACTIVE bond total_count")
        assert ids_of(active_rows) == [second_bond["id"]]

        released_rows, released_meta = validate_paginated(
            api.list_bonds(licensee["id"], officer_headers, params={"status": "RELEASED"})
        )
        assert_total_count(released_meta, 1, "RELEASED bond total_count")
        assert ids_of(released_rows) == [first_bond["id"]]
        assert_bond_instrument(
            released_rows[0], "RELEASED", "SUPERSEDED_BY_NEW_BOND", amount_cents=900000
        )

        reread = world.licensee(licensee["id"])
        assert_bond_position(
            reread, posted_bond_cents=1500000, bond_deficiency_cents=0
        )

    def test_suspending_a_pending_bond_licensee_is_refused_without_doubling_the_bond(
        self, api, world, officer_headers
    ):
        """Suspension is declared only out of ACTIVE, so the 2.0 multiplier never runs here.

        PRD: "Requesting a transition the current `status` does not admit — reinstating an already
        `ACTIVE` licensee, suspending one that is not `ACTIVE`, or touching one that is already
        `REVOKED` — fails with `ERR_LICENSEE_STATE_INVALID` (HTTP 409)."
        PRD: "Suspension is the mirror image. `status` becomes `SUSPENDED`, `required_bond_cents`
        is recomputed with the suspension multiplier at 2.0 and `bond_deficiency_cents` re-derived
        from it, and *only if* that re-derived deficiency is greater than zero, every refund claim
        of the licensee whose `status` is `SUBMITTED` or `REVIEWED` has its current status copied
        into `status_before_hold`, its `status` set to `HELD` and its `hold_reason` set to
        `BOND_DEFICIENCY`."

        Design: Corner/state_machines/suspend_from_pending_bond_returns_licensee_state_invalid
        """
        licensee = world.new_licensee("DISTRIBUTOR", legal_name="Sierra Distribution Inc")

        response = api.suspend_licensee(
            licensee["id"], "Desk error - the licensee is not yet in force", officer_headers
        )

        validate_error(response, ApiErrorId.LICENSEE_STATE_INVALID, expected_status=409)
        reread = world.licensee(licensee["id"])
        assert reread["status"] == "PENDING_BOND"
        assert_bond_position(reread, required_bond_cents=1500000)

    def test_a_revoked_licence_admits_no_further_transition(self, api, world, officer_headers):
        """REVOKED is terminal, and its own gate outranks the transition-legality gate.

        PRD: "Separately, a `REVOKED` licensee accepts no new bonds, no reinstatement, no
        suspension, no new returns, no return filing and no new refund claims; those attempts fail
        with `ERR_LICENSEE_REVOKED` (HTTP 409)."

        Design: Corner/state_machines/revoked_licensee_cannot_be_reactivated
        """
        licensee = world.new_licensee("DISTRIBUTOR", legal_name="Victor Distribution Inc")
        revoked = world.revoke(licensee["id"], "Application withdrawn and licence denied")
        assert revoked["status"] == "REVOKED"

        response = api.activate_licensee(licensee["id"], officer_headers)

        validate_error(response, ApiErrorId.LICENSEE_REVOKED, expected_status=409)
        assert world.licensee(licensee["id"])["status"] == "REVOKED"

        suspend_response = api.suspend_licensee(
            licensee["id"], "Attempted suspension of a revoked licence", officer_headers
        )
        validate_error(suspend_response, ApiErrorId.LICENSEE_REVOKED, expected_status=409)
        assert world.licensee(licensee["id"])["status"] == "REVOKED"

    def test_one_revoke_forfeits_the_bond_and_revokes_the_certificate(
        self, api, world, officer_headers
    ):
        """A single revoke drives the bond machine and the certificate machine in one request.

        PRD: "Every bond instrument of the licensee whose `status` is `ACTIVE` becomes `FORFEITED`
        with `release_reason` set to `LICENSE_REVOKED`, while instruments already `RELEASED` are
        left untouched — so a revoked licensee whose bonds were previously released carries a full
        deficiency once `posted_bond_cents` and `bond_deficiency_cents` are re-derived."
        PRD: "Every exemption certificate naming this licensee as its purchaser and still `ACTIVE`
        becomes `REVOKED`."

        Design: Corner/state_machines/licensee_revoke_cascades_certificates_and_forfeits_bonds
        """
        licensee = world.new_licensee("DISTRIBUTOR", legal_name="Zulu Distribution Inc")
        bond = world.post_bond(licensee["id"], 1500000, surety_name="Granite Surety Co")
        world.activate(licensee["id"])
        certificate = world.certificate(
            licensee["id"],
            exemption_type="GOVERNMENT",
            document_number="CERT-REV-0001",
            valid_from="2026-01-01",
            valid_to="2026-12-31",
        )
        assert certificate["status"] == "ACTIVE"

        response = api.revoke_licensee(
            licensee["id"], "Repeated failure to remit; licence revoked by order", officer_headers
        )

        revoked = validate_success(response, expected_status=200)
        assert revoked["status"] == "REVOKED"

        _active_rows, active_meta = validate_paginated(
            api.list_bonds(licensee["id"], officer_headers, params={"status": "ACTIVE"})
        )
        assert_total_count(active_meta, 0, "ACTIVE bond total_count after revocation")

        forfeited_rows, forfeited_meta = validate_paginated(
            api.list_bonds(licensee["id"], officer_headers, params={"status": "FORFEITED"})
        )
        assert_total_count(forfeited_meta, 1, "FORFEITED bond total_count")
        assert ids_of(forfeited_rows) == [bond["id"]]
        assert_bond_instrument(forfeited_rows[0], "FORFEITED", "LICENSE_REVOKED")

        cert_reread = validate_success(
            api.get_certificate(certificate["id"], officer_headers)
        )
        assert cert_reread["status"] == "REVOKED"

        assert_bond_position(world.licensee(licensee["id"]), posted_bond_cents=0)


class TestReturnAndInspectionEdges:
    def test_filing_a_return_twice_is_refused_and_posts_nothing_a_second_time(
        self, api, world, officer_headers, examiner_headers
    ):
        """Filing is not idempotent: the retry is refused, so the ledger cannot be double-posted.

        PRD: "The return's `filing_status` must be `DRAFT` (`ERR_RETURN_ALREADY_FILED`)."
        PRD: "For an **original** return — one whose `amends_return_id` is null — a `RETURN_TAX`
        entry for the full `tax_due_cents` is appended always, even when the tax is zero; an
        `INTEREST` entry for `interest_cents` is appended only when interest is greater than zero;
        and a `PENALTY` entry for `penalty_cents` is appended only when the penalty is greater than
        zero."
        PRD: "When `days_late` is 1 or more **and** the return is an original, `late_filing_count`
        increases by one; a period is counted late exactly once, on its original filing, so
        amending an already-late period does not count it again."

        Design: Corner/state_machines/second_file_on_a_filed_return_returns_return_already_filed
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Whiskey Fuel Supply LLC")
        filer = world.new_licensee("DISTRIBUTOR", legal_name="Xray Distribution Inc")
        built = world.filed_return(
            filer["id"],
            "2026-07",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "UNDYED_DIESEL",
                    "total": 50.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 50.00,
                            "date": "2026-07-12",
                        }
                    ],
                }
            ],
            attest_name="X. Xray",
        )
        assert_return_statuses(built.row, "FILED")

        response = api.file_return(built.id, "X. Xray", examiner_headers)

        validate_error(response, ApiErrorId.RETURN_ALREADY_FILED, expected_status=409)
        reread = validate_success(api.get_return(built.id, examiner_headers))
        assert_return_statuses(reread, "FILED")
        assert_return_money(reread, tax_due_cents=0, days_late=0)

        entries, meta = validate_paginated(
            api.list_ledger_entries(filer["id"], officer_headers)
        )
        assert_total_count(meta, 1, "ledger total_count after one accepted and one refused filing")
        assert_ledger_row(
            entries[0], "RETURN_TAX", 0, source_entity_type="MonthlyReturn", source_entity_id=built.id
        )
        assert world.licensee(filer["id"])["late_filing_count"] == 0

    def test_dismissing_a_negative_inspection_is_refused_because_nothing_was_assessed(
        self, api, world, supervisor_headers
    ):
        """DISMISSED is reachable only from PENALTY_ASSESSED, and a NEGATIVE stop never gets there.

        PRD: "A `NEGATIVE` result is recorded and nothing else happens: `status` stays `RECORDED`,
        `penalty_cents` is 0, and no ledger row is written."
        PRD: "A `TaxSupervisor` may dismiss an inspection whose `status` is `PENALTY_ASSESSED`,
        supplying a `dismissal_reason`; from `RECORDED` or `DISMISSED` the request fails with
        `ERR_INSPECTION_NOT_DISMISSIBLE` (HTTP 409)."

        Design: Corner/state_machines/dismiss_on_a_negative_inspection_returns_inspection_not_dismissible
        """
        retailer = world.new_licensee(
            "RETAILER", legal_name="Yankee Retail Stops LLC", retail_channel="HIGHWAY"
        )
        inspection = world.inspection(
            retailer["id"],
            dye_test_result="NEGATIVE",
            gallons_in_tank=80.00,
            inspection_date="2026-07-20",
            vehicle_identifier="MN-TRK-4417",
            location_description="US-10 westbound scale",
        )
        assert inspection["status"] == "RECORDED"

        response = api.dismiss_inspection(
            inspection["id"], "Operator produced a clean retest", supervisor_headers
        )

        validate_error(response, ApiErrorId.INSPECTION_NOT_DISMISSIBLE, expected_status=409)
        reread = validate_success(api.get_inspection(inspection["id"], supervisor_headers))
        assert reread["status"] == "RECORDED"
        assert reread["penalty_cents"] == 0
        assert reread["prior_positive_count"] == 0

        licensee = world.licensee(retailer["id"])
        assert licensee["dyed_violation_count"] == 0
        assert licensee["balance_cents"] == 0


class TestRefundClaimMachine:
    def test_a_new_claim_lands_in_submitted_with_the_money_already_computed(
        self, api, world, examiner_headers
    ):
        """The initial state carries the computed money and no workflow footprint at all.

        PRD: "`refund_amount_cents` is `allowable_gallons` multiplied by 30.9 cents per gallon,
        rounded half up to a whole cent, exactly once."
        PRD: "The claim is stored with `status` `SUBMITTED` and all of `status_before_hold`,
        `hold_reason`, `recommendation`, `recommended_gallons`, `reviewer_user_id`,
        `decider_user_id` and `payment_reference` null."

        Design: Corner/state_machines/refund_claim_initial_state_is_submitted
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Tango Fuel Supply LLC")
        claimant = world.new_licensee("DISTRIBUTOR", legal_name="Uniform Distribution Inc")
        world.set_clock("2026-09-05T00:00:00Z")
        built = world.filed_return(
            claimant["id"],
            "2026-08",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "UNDYED_DIESEL",
                    "total": 100.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 100.00,
                            "date": "2026-08-14",
                        }
                    ],
                }
            ],
            attest_name="U. Uniform",
        )

        response = api.create_refund_claim(
            refund_claim_payload(claimant["id"], "2026-08", 100.00, "OFF_ROAD"),
            world.agent(claimant["id"]),
        )

        claim = validate_success(response, expected_status=201)
        assert claim["status"] == "SUBMITTED"
        assert_claim_money(claim, 100.00, 3090)
        assert refund_cents_for(100.00) == 3090
        assert_nulls(
            claim,
            [
                "reviewer_user_id",
                "decider_user_id",
                "hold_reason",
                "status_before_hold",
                "recommendation",
                "recommended_gallons",
                "payment_reference",
            ],
        )

        reread = validate_success(api.get_return(built.id, examiner_headers))
        assert_return_statuses(reread, "FILED")
        assert_return_money(reread, tax_due_cents=0, days_late=0)

    def test_paying_a_merely_reviewed_claim_is_refused_and_posts_no_refund_row(
        self, api, world, officer_headers, supervisor_headers
    ):
        """PAID is reachable only from APPROVED or PARTIALLY_APPROVED, so the decision is unskippable.

        PRD: "A `TaxSupervisor` pays a claim from `APPROVED` or `PARTIALLY_APPROVED`, supplying a
        `payment_reference` for the warrant or ACH transfer."
        PRD: "Paying from any other status, including `HELD`, fails with
        `ERR_REFUND_STATE_INVALID`."

        Design: Corner/state_machines/refund_pay_from_reviewed_returns_refund_state_invalid
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Tango Fuel Supply LLC")
        claimant = world.new_licensee("DISTRIBUTOR", legal_name="Uniform Distribution Inc")
        world.set_clock("2026-09-05T00:00:00Z")
        world.filed_return(
            claimant["id"],
            "2026-08",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "UNDYED_DIESEL",
                    "total": 100.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 100.00,
                            "date": "2026-08-14",
                        }
                    ],
                }
            ],
            attest_name="U. Uniform",
        )
        claim = world.refund_claim(claimant["id"], "2026-08", 100.00)
        reviewed = world.review_claim(claim["id"], "APPROVE")
        assert reviewed["status"] == "REVIEWED"

        response = api.pay_claim(
            claim["id"], {"payment_reference": "WARRANT-0001"}, supervisor_headers
        )

        validate_error(response, ApiErrorId.REFUND_STATE_INVALID, expected_status=409)
        reread = validate_success(api.get_refund_claim(claim["id"], supervisor_headers))
        assert reread["status"] == "REVIEWED"
        assert reread["reviewer_user_id"] == RETURNS_EXAMINER_ID
        assert_nulls(reread, ["decider_user_id", "payment_reference"])

        _rows, meta = validate_paginated(
            api.list_ledger_entries(
                claimant["id"], officer_headers, params={"entry_type": "REFUND"}
            )
        )
        assert_total_count(meta, 0, "REFUND ledger total_count after a refused payment")


class TestDiscrepancyMachine:
    def test_resolving_the_only_discrepancy_as_explained_bubbles_the_purchaser_return(
        self, api, world, examiner_headers, officer_headers
    ):
        """EXPLAINED closes the finding, moves the purchaser's return on and keeps the run's gallons.

        PRD: "`EXPLAINED` sets `status` to `RESOLVED_EXPLAINED` and leaves the run's
        `unreported_gallons_total` and `written_off_gallons_total` exactly as they were."
        PRD: "And all three then check the purchaser's return: if no discrepancy naming that
        `distributor_return_id` remains in `OPEN`, `INQUIRY_SENT` or `RESPONSE_RECEIVED`, the
        return's `match_status` moves from `MATCH_VARIANCE` to `MATCH_RESOLVED`."
        PRD: "All three branches decrease the purchaser's `open_discrepancy_count` by one and
        re-derive the purchaser's `unreported_gallons_total`, so an explained, written-off or
        escalated variance drops out of the licensee-level figure that feeds risk scoring even
        where it stays in the run-level figure."

        Design: Corner/state_machines/discrepancy_resolve_explained_bubbles_both_returns_to_match_resolved
        """
        world.set_clock("2026-09-05T00:00:00Z")
        cell = world.unreported_cell(1000.00, 900.00, "2026-08", "GASOLINE")
        discrepancy = cell["discrepancy"]
        assert discrepancy["status"] == "OPEN"
        assert discrepancy["direction"] == "UNREPORTED_BY_PURCHASER"
        assert_return_statuses(
            validate_success(api.get_return(cell["distributor_return"].id, examiner_headers)),
            "FILED",
            "MATCH_VARIANCE",
        )

        response = api.resolve_discrepancy(
            discrepancy["id"], resolve_payload("EXPLAINED"), examiner_headers
        )

        resolved = validate_success(response, expected_status=200)
        assert resolved["status"] == "RESOLVED_EXPLAINED"
        assert_gallons(resolved["variance_gallons"], 100.00, "variance_gallons")

        purchaser_return = validate_success(
            api.get_return(cell["distributor_return"].id, examiner_headers)
        )
        assert_return_statuses(purchaser_return, "FILED", "MATCH_RESOLVED")

        purchaser = world.licensee(cell["distributor"]["id"])
        assert purchaser["open_discrepancy_count"] == 0
        assert_gallons(purchaser["unreported_gallons_total"], 0.00, "unreported_gallons_total")

        run = validate_success(api.get_cross_match_run(cell["run"]["id"], examiner_headers))
        assert run["discrepancy_count"] == 1
        assert_gallons(
            run["gross_unreported_gallons_total"], 100.00, "gross_unreported_gallons_total"
        )
        assert_gallons(run["unreported_gallons_total"], 100.00, "run unreported_gallons_total")
        assert_gallons(run["written_off_gallons_total"], 0.00, "written_off_gallons_total")

    def test_a_fourth_inquiry_on_one_discrepancy_is_refused_at_the_round_limit(
        self, api, world, examiner_headers
    ):
        """The inquiry/response loop is bounded at three rounds and the fourth send is refused.

        PRD: "At most three inquiries may ever be sent on one discrepancy: the round counter must
        be below 3 before a new inquiry, so the third round is the last permitted one and a fourth
        attempt fails with `ERR_INQUIRY_ROUND_LIMIT` (HTTP 422)."

        Design: Corner/state_machines/fourth_inquiry_on_one_discrepancy_returns_inquiry_round_limit
        """
        world.set_clock("2026-09-05T00:00:00Z")
        cell = world.unreported_cell(1000.00, 900.00, "2026-08", "GASOLINE")
        discrepancy = cell["discrepancy"]
        purchaser_id = cell["distributor"]["id"]
        world.send_inquiry(
            discrepancy["id"],
            question="Round 1: identify the missing 100.00 GASOLINE gallons",
            response_due_date="2026-09-20",
        )
        world.answer_inquiry(
            discrepancy["id"],
            purchaser_id,
            explanation="Round 1: the load was received in the following period",
        )
        world.send_inquiry(
            discrepancy["id"],
            question="Round 2: supply the bill of lading for the claimed later receipt",
            response_due_date="2026-09-25",
        )
        world.answer_inquiry(
            discrepancy["id"],
            purchaser_id,
            explanation="Round 2: the bill of lading cannot be located",
        )
        third_question = "Round 3: final request for the terminal receipt record"
        world.send_inquiry(
            discrepancy["id"], question=third_question, response_due_date="2026-09-30"
        )
        answered = world.answer_inquiry(
            discrepancy["id"], purchaser_id, explanation="Round 3: no further records exist"
        )
        assert answered["inquiry_round"] == 3
        assert answered["status"] == "RESPONSE_RECEIVED"

        response = api.send_inquiry(
            discrepancy["id"],
            {"question": "Round 4: one more attempt", "response_due_date": "2026-10-05"},
            examiner_headers,
        )

        validate_error(response, ApiErrorId.INQUIRY_ROUND_LIMIT, expected_status=422)
        reread = validate_success(api.get_discrepancy(discrepancy["id"], examiner_headers))
        assert reread["inquiry_round"] == 3
        assert reread["status"] == "RESPONSE_RECEIVED"
        assert reread["last_question"] == third_question
        assert world.licensee(purchaser_id)["open_discrepancy_count"] == 1

    def test_auto_escalation_is_skipped_when_an_overlapping_case_already_exists(
        self, api, world, examiner_headers, manager_headers
    ):
        """An 11000.00-gallon finding stays OPEN because a non-closed case already covers the period.

        PRD: "If, however, a non-closed audit case for that same subject already overlaps the run's
        period under the buffered-overlap rule of §3.9, no case is created: the discrepancy is left
        `OPEN`, it counts in the purchaser's `open_discrepancy_count` like any other open finding,
        and `escalation_skipped_count` increments instead."
        PRD: "Every cell examined increments `matched_cells_count`, whether or not it produces a
        finding."
        PRD: "Once the cells are enumerated, every filed return of the period is stamped: a return
        whose licensee appears in no discrepancy this run created moves to `MATCH_CLEAN`, and every
        other filed return of the period moves to `MATCH_VARIANCE`."

        Design: Corner/state_machines/auto_escalation_is_skipped_when_an_overlapping_audit_case_exists
        """
        world.set_clock("2026-09-05T00:00:00Z")
        cell = world.unreported_cell(12000.00, 1000.00, "2026-08", "GASOLINE", run=False)
        purchaser_id = cell["distributor"]["id"]
        case = world.audit_case(
            purchaser_id, "2026-08", "2026-08", as_headers=manager_headers
        )
        assert case["case_status"] != "CLOSED"

        response = api.create_cross_match_run({"period_month": "2026-08"}, examiner_headers)

        run = validate_success(response, expected_status=201)
        assert run["discrepancy_count"] == 1
        assert run["matched_cells_count"] == 1
        assert run["escalated_count"] == 0
        assert run["escalation_skipped_count"] == 1
        assert_gallons(
            run["gross_unreported_gallons_total"], 11000.00, "gross_unreported_gallons_total"
        )
        assert_gallons(run["unreported_gallons_total"], 11000.00, "run unreported_gallons_total")

        rows, meta = validate_paginated(
            api.list_discrepancies(examiner_headers, params={"run_id": run["id"]})
        )
        assert_total_count(meta, 1, "discrepancy total_count for the run")
        assert rows[0]["status"] == "OPEN"
        assert rows[0]["direction"] == "UNREPORTED_BY_PURCHASER"
        assert_gallons(rows[0]["variance_gallons"], 11000.00, "variance_gallons")

        case_rows, case_meta = validate_paginated(
            api.list_audit_cases(
                manager_headers, params={"subject_licensee_id": purchaser_id}
            )
        )
        assert_total_count(case_meta, 1, "audit case total_count for the subject")
        assert ids_of(case_rows) == [case["id"]]

        purchaser = world.licensee(purchaser_id)
        assert purchaser["open_audit_count"] == 1
        assert purchaser["open_discrepancy_count"] == 1
        assert_return_statuses(
            validate_success(api.get_return(cell["distributor_return"].id, examiner_headers)),
            "FILED",
            "MATCH_VARIANCE",
        )
