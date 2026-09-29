"""Endpoint surfaces: CRUD round trips, action verbs and computed reads."""

from test_helpers import (
    ApiErrorId,
    assert_assessment_money,
    assert_balance_matches_ledger,
    assert_bond_instrument,
    assert_bond_position,
    assert_case_dimensions,
    assert_cents,
    assert_claim_hold,
    assert_claim_money,
    assert_claim_not_held,
    assert_gallons,
    assert_imposition,
    assert_ledger_row,
    assert_ledger_sequence,
    assert_mutable_common_fields,
    assert_total_count,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    audit_case_payload,
    rack_removal_payload,
    refund_claim_payload,
    terminal_payload,
)


class TestTerminalSurface:
    def test_terminal_create_read_and_list_before_a_duplicate_control_number_is_refused(
        self, api, world, officer_headers
    ):
        """Terminals are create-read-list only, and their control number is claimed for good.

        PRD: "Terminals are registered by a `LicensingOfficer` with their IRS
        `terminal_control_number` — the letter `T`, two digits, two uppercase letters and four
        digits — a trade `name`, and the two-letter `state_code` of the state the rack physically
        sits in. The control number is unique across all terminals; a collision is refused with
        `ERR_DUPLICATE_TCN` (HTTP 409). Terminals are otherwise inert reference data and may be
        listed filtered by `state_code`."
        PRD: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and
        `has_more`, where `total_count` is the number of rows matching the filters before
        pagination is applied."

        Design: Corner/endpoints/terminal_create_read_list_round_trip_with_a_duplicate_tcn_refusal
        """
        wisconsin = validate_success(
            api.create_terminal(
                terminal_payload(
                    name="Superior Harbor Terminal",
                    state_code="WI",
                    terminal_control_number="T66WI6600",
                ),
                officer_headers,
            ),
            expected_status=201,
        )

        response = api.create_terminal(
            terminal_payload(
                name="Rosemount Rack Terminal",
                state_code="MN",
                terminal_control_number="T66MN6600",
            ),
            officer_headers,
        )

        created = validate_success(response, expected_status=201)
        assert created["terminal_control_number"] == "T66MN6600"
        assert created["name"] == "Rosemount Rack Terminal"
        assert created["state_code"] == "MN"
        assert_mutable_common_fields(created, expected_version=1)

        reread = validate_success(api.get_terminal(created["id"], world.examiner))
        assert reread["id"] == created["id"]
        assert reread["terminal_control_number"] == created["terminal_control_number"]
        assert reread["name"] == created["name"]
        assert reread["state_code"] == created["state_code"]
        assert reread["version"] == created["version"]

        mn_rows, mn_meta = validate_paginated(
            api.list_terminals(officer_headers, params={"state_code": "MN"})
        )
        assert_total_count(mn_meta, 1, "terminals in MN")
        assert mn_meta["has_more"] is False, "a single matching row leaves nothing more to fetch"
        assert ids_of(mn_rows) == [created["id"]]
        wi_rows, wi_meta = validate_paginated(
            api.list_terminals(officer_headers, params={"state_code": "WI"})
        )
        assert_total_count(wi_meta, 1, "terminals in WI")
        assert ids_of(wi_rows) == [wisconsin["id"]]

        page_rows, page_meta = validate_paginated(
            api.list_terminals(officer_headers, params={"limit": 1, "offset": 0})
        )
        assert len(page_rows) == 1, "limit 1 must cap the page at one row"
        assert_total_count(page_meta, 2, "total_count counts the unfiltered set")
        assert page_meta["has_more"] is True, "one of two rows leaves more to fetch"

        duplicate = api.create_terminal(
            terminal_payload(
                name="Copycat Rack Terminal",
                state_code="MN",
                terminal_control_number="T66MN6600",
            ),
            officer_headers,
        )
        validate_error(duplicate, ApiErrorId.DUPLICATE_TCN, expected_status=409)
        _rows, after_meta = validate_paginated(api.list_terminals(officer_headers))
        assert_total_count(after_meta, 2, "terminal total_count after a refused create")


class TestBondReleaseAction:
    def test_releasing_a_pending_licensees_bond_succeeds_while_an_active_ones_is_refused(
        self, api, world
    ):
        """The same release verb answers differently by what the principal licensee still needs.

        PRD: "Operator release is the deliberate, non-superseding path out of `ACTIVE`, and it
        exists mainly so that over-collateralized licensees can free capital. Releasing sets
        `status` to `RELEASED` with `release_reason` `OPERATOR_RELEASE`, re-derives the licensee's
        `posted_bond_cents` and `bond_deficiency_cents`, and increments the versions of both rows.
        An instrument that is not `ACTIVE` cannot be released and the attempt fails with
        `ERR_BOND_NOT_ACTIVE` (HTTP 409)."
        PRD: "And a release that would leave an `ACTIVE` licensee with `posted_bond_cents` below
        `required_bond_cents` is refused with `ERR_BOND_RELEASE_WOULD_CREATE_DEFICIENCY` (HTTP
        422); that fiscal check runs last, after the instrument's own state check."

        Design: Corner/endpoints/bond_release_action_frees_a_pending_licensee_and_is_refused_for_an_active_one
        """
        pending = world.new_licensee(
            "DISTRIBUTOR", legal_name="Release Pending Distribution Inc"
        )
        pending_bond = world.post_bond(pending["id"], 1500000)
        active = world.new_licensee("SUPPLIER", legal_name="Release Active Fuel Supply LLC")
        active_bond = world.post_bond(active["id"], 1500000)
        world.activate(active["id"])

        response = api.release_bond(pending_bond["id"], world.officer)

        released = validate_success(response)
        assert_bond_instrument(
            released, "RELEASED", "OPERATOR_RELEASE", amount_cents=1500000
        )
        assert (
            released["version"] > pending_bond["version"]
        ), "releasing an instrument increments its own version"

        freed = world.licensee(pending["id"])
        assert_bond_position(
            freed,
            required_bond_cents=1500000,
            posted_bond_cents=0,
            bond_deficiency_cents=1500000,
        )
        assert (
            freed["status"] == "PENDING_BOND"
        ), "a release is not a licensee-status action, so PENDING_BOND is left alone"
        _rows, pending_meta = validate_paginated(
            api.list_bonds(pending["id"], world.officer, params={"status": "ACTIVE"})
        )
        assert_total_count(pending_meta, 0, "ACTIVE bonds of the released licensee")

        refused = api.release_bond(active_bond["id"], world.officer)
        validate_error(
            refused, ApiErrorId.BOND_RELEASE_WOULD_CREATE_DEFICIENCY, expected_status=422
        )
        held_rows, held_meta = validate_paginated(
            api.list_bonds(active["id"], world.officer, params={"status": "ACTIVE"})
        )
        assert_total_count(held_meta, 1, "the refused release leaves the instrument ACTIVE")
        assert ids_of(held_rows) == [active_bond["id"]]
        assert_bond_position(
            world.licensee(active["id"]),
            required_bond_cents=1500000,
            posted_bond_cents=1500000,
            bond_deficiency_cents=0,
        )

        again = api.release_bond(pending_bond["id"], world.officer)
        validate_error(again, ApiErrorId.BOND_NOT_ACTIVE, expected_status=409)


class TestRackRemovalLinks:
    def test_a_rack_removal_joins_three_references_and_404s_on_an_unused_one(self, api, world):
        """One POST joins terminal, position holder and purchaser, and each link is a filter.

        PRD: "**Body foreign keys**, in the order the fields are declared on the request:
        identifiers naming a licensee (`licensee_id`, `parent_licensee_id`,
        `purchaser_licensee_id`, `position_holder_licensee_id`, `counterparty_licensee_id`,
        `inspected_licensee_id`, `subject_licensee_id`) resolve to a licensee or the request fails
        with `ERR_LICENSEE_NOT_FOUND`; `terminal_id` resolves or fails with
        `ERR_TERMINAL_NOT_FOUND`; a non-null `exemption_certificate_id` resolves or fails with
        `ERR_CERTIFICATE_NOT_FOUND`; a non-null `source_discrepancy_id` resolves or fails with
        `ERR_DISCREPANCY_NOT_FOUND`."
        PRD: "Otherwise — a `BLENDER`, `TRANSPORTER` or `RETAILER` purchaser, or a suspended
        supplier or distributor — `imposition_point` is `TERMINAL_RACK`."

        Design: Corner/endpoints/rack_removal_links_terminal_holder_and_purchaser_and_404s_on_a_missing_terminal
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Link Fuel Supply LLC", gross_net_election="NET"
        )
        # The purchaser's status must be ACTIVE or SUSPENDED to take delivery at
        # a rack at all, so the retailer is bonded and activated first.
        retailer = world.active_licensee(
            "RETAILER", legal_name="Link Farm Depot LLC", retail_channel="FARM"
        )
        terminal = world.terminal(name="Link River Terminal", state_code="MN")

        response = api.create_rack_removal(
            rack_removal_payload(
                terminal["id"],
                supplier["id"],
                retailer["id"],
                product_code="GASOLINE",
                gross_gallons=1010.00,
                net_gallons=1000.00,
                removal_date="2026-07-24",
                destination_state="MN",
            ),
            world.examiner,
        )

        created = validate_success(response, expected_status=201)
        assert created["terminal_id"] == terminal["id"]
        assert created["position_holder_licensee_id"] == supplier["id"]
        assert created["purchaser_licensee_id"] == retailer["id"]
        assert_imposition(
            created,
            basis_used="NET",
            imposition_point="TERMINAL_RACK",
            taxable_gallons=1000.00,
            tax_imposed=True,
            tax_amount_cents=28600,
            deferred_tax_cents=0,
        )

        for label, params in (
            ("terminal_id", {"terminal_id": terminal["id"]}),
            ("position_holder_licensee_id", {"position_holder_licensee_id": supplier["id"]}),
            ("purchaser_licensee_id", {"purchaser_licensee_id": retailer["id"]}),
        ):
            rows, meta = validate_paginated(
                api.list_rack_removals(world.examiner, params=params)
            )
            assert_total_count(meta, 1, f"rack removals under the {label} filter")
            assert ids_of(rows) == [created["id"]], f"the {label} filter must find the row"

        missing_terminal = api.create_rack_removal(
            rack_removal_payload(
                "00000000-0000-4000-8000-000000006801",
                supplier["id"],
                retailer["id"],
                product_code="GASOLINE",
                gross_gallons=1010.00,
                net_gallons=1000.00,
                removal_date="2026-07-24",
                destination_state="MN",
            ),
            world.examiner,
        )
        validate_error(missing_terminal, ApiErrorId.TERMINAL_NOT_FOUND, expected_status=404)

        missing_purchaser = api.create_rack_removal(
            rack_removal_payload(
                terminal["id"],
                supplier["id"],
                "00000000-0000-4000-8000-000000006802",
                product_code="GASOLINE",
                gross_gallons=1010.00,
                net_gallons=1000.00,
                removal_date="2026-07-24",
                destination_state="MN",
            ),
            world.examiner,
        )
        validate_error(missing_purchaser, ApiErrorId.LICENSEE_NOT_FOUND, expected_status=404)

        reread = validate_success(api.get_rack_removal(created["id"], world.examiner))
        assert reread["id"] == created["id"]
        _rows, final_meta = validate_paginated(api.list_rack_removals(world.examiner))
        assert_total_count(final_meta, 1, "rack removals after the two refused reports")


def _subject_with_one_late_filing_and_one_violation(world, tag):
    """One late 2026-08 filing plus one positive dye test: 8 + 15 points under both readings."""
    supplier = world.new_licensee("SUPPLIER", legal_name=f"{tag} Fuel Supply LLC")
    subject = world.new_licensee("DISTRIBUTOR", legal_name=f"{tag} Distribution Inc")
    world.inspection(
        subject["id"],
        "POSITIVE",
        40.00,
        "2026-07-30",
        vehicle_identifier="MN-TRK-6900",
    )
    world.set_clock("2026-10-05T00:00:00Z")
    world.build_return(
        subject["id"],
        "2026-08",
        [
            {
                "code": "SCH_2_RECEIVED_TAX_UNPAID",
                "product": "GASOLINE",
                "total": 1000.00,
                "lines": [
                    {
                        "counterparty": supplier["id"],
                        "gallons": 1000.00,
                        "date": "2026-08-15",
                    }
                ],
            }
        ],
        file=True,
        attest_name="R. Risk",
    )
    return subject


class TestRiskReads:
    def test_the_risk_profile_publishes_both_weightings_and_the_gate_constant(
        self, api, world, manager_headers
    ):
        """Both readings share the two behaviour terms, so a clean cross-match record ties them.

        PRD: "The risk profile of a licensee can be read individually by an `AuditManager`,
        `TaxSupervisor` or `ReturnsExaminer`, and the read deliberately returns **both** scoring
        variants side by side together with the inputs that produced them:
        `risk_score_variance_weighted`, `risk_score_frequency_weighted`,
        `unreported_gallons_total`, `open_discrepancy_count`, `late_filing_count`,
        `dyed_violation_count`, and `audit_selection_threshold`, the selection cut-off of 60
        points."
        PRD: "Late-filing points are 8 points per unit of `late_filing_count`, capped at 24.
        Dyed-fuel points are 15 points per unit of `dyed_violation_count`, capped at 30."

        Design: Corner/endpoints/risk_profile_read_exposes_both_weightings_and_the_gate_constant
        """
        subject = _subject_with_one_late_filing_and_one_violation(world, "Risk Read")

        response = api.get_risk_profile(subject["id"], manager_headers)

        profile = validate_success(response)
        assert profile["risk_score_variance_weighted"] == 23, (
            "8 late-filing points plus 15 dyed-fuel points with a zero magnitude term is 23"
        )
        assert profile["risk_score_frequency_weighted"] == 23, (
            "8 late-filing points plus 15 dyed-fuel points with a zero count term is 23"
        )
        assert_gallons(profile["unreported_gallons_total"], 0.00, "unreported_gallons_total")
        assert profile["open_discrepancy_count"] == 0
        assert profile["late_filing_count"] == 1, "the 2026-08 return was filed 15 days late"
        assert profile["dyed_violation_count"] == 1
        assert (
            profile["audit_selection_threshold"] == 60
        ), "the read publishes the 60-point selection cut-off alongside the scores"

        row = world.licensee(subject["id"])
        assert row["risk_score_variance_weighted"] == 23, (
            "the entity row and the computed read cannot disagree"
        )
        assert row["risk_score_frequency_weighted"] == 23
        assert row["late_filing_count"] == 1
        assert row["dyed_violation_count"] == 1

    def test_risk_score_selection_is_refused_below_the_gate_while_a_referral_is_not(
        self, api, world, manager_headers
    ):
        """The threshold gate is conditional on selection_method, not on the subject's history.

        PRD: "`risk_score_variant` is consulted only when `selection_method` is `RISK_SCORE`; for
        the other two methods it is ignored. Under `RISK_SCORE` the subject's score in the chosen
        variant must reach 60 points, and a subject below the threshold is refused with
        `ERR_RISK_SCORE_BELOW_THRESHOLD` (HTTP 422). `selection_score` freezes the score of the
        chosen variant on the case, and is 0 for any method other than `RISK_SCORE` — the frozen
        figure documents why the case was opened even after the underlying discrepancies are worked
        and the live score moves."
        PRD: "Opening the case increments the subject's `open_audit_count` and, because that count
        is now positive, moves the subject's `SUBMITTED` and `REVIEWED` refund claims to `HELD`
        with `hold_reason` `OPEN_AUDIT`."

        Design: Corner/endpoints/risk_score_selection_is_refused_below_the_gate_while_manual_referral_is_not
        """
        subject = _subject_with_one_late_filing_and_one_violation(world, "Gate")

        response = api.create_audit_case(
            audit_case_payload(
                subject["id"],
                "2026-08",
                "2026-08",
                selection_method="RISK_SCORE",
                risk_score_variant="VARIANCE_WEIGHTED",
            ),
            manager_headers,
        )

        validate_error(response, ApiErrorId.RISK_SCORE_BELOW_THRESHOLD, expected_status=422)
        frequency = api.create_audit_case(
            audit_case_payload(
                subject["id"],
                "2026-08",
                "2026-08",
                selection_method="RISK_SCORE",
                risk_score_variant="FREQUENCY_WEIGHTED",
            ),
            manager_headers,
        )
        validate_error(frequency, ApiErrorId.RISK_SCORE_BELOW_THRESHOLD, expected_status=422)
        _rows, meta = validate_paginated(
            api.list_audit_cases(
                manager_headers, params={"subject_licensee_id": subject["id"]}
            )
        )
        assert_total_count(meta, 0, "audit cases after the two refused openings")
        assert world.licensee(subject["id"])["open_audit_count"] == 0

        referral = validate_success(
            api.create_audit_case(
                audit_case_payload(
                    subject["id"], "2026-08", "2026-08", selection_method="ROADSIDE_REFERRAL"
                ),
                manager_headers,
            ),
            expected_status=201,
        )
        assert_case_dimensions(referral, "OPEN", "NONE")
        assert referral["selection_method"] == "ROADSIDE_REFERRAL"
        assert (
            referral["selection_score"] == 0
        ), "selection_score is 0 for any method other than RISK_SCORE"
        assert (
            world.licensee(subject["id"])["open_audit_count"] == 1
        ), "opening the referral case increments open_audit_count"


class TestAuditCaseActions:
    def test_closing_a_case_is_refused_while_its_assessment_is_protested(
        self, api, world, manager_headers
    ):
        """The two case dimensions couple in exactly one place: the close.

        PRD: "Closing the case is the one and only place the two dimensions are coupled:
        `assessment_status` must be `NONE`, `FINAL` or `ABATED`. An assessment still sitting at
        `ISSUED` or `PROTESTED` must be finalized or abated before the case can close, and a
        premature closure is refused with `ERR_ASSESSMENT_PENDING_DISPOSITION` (HTTP 409). Closure
        decrements the subject's `open_audit_count`, and when that count reaches zero, every refund
        claim of that licensee at `HELD` with `hold_reason` `OPEN_AUDIT` reverts to its
        `status_before_hold`."
        PRD: "A `TaxSupervisor` finalizes from `ISSUED` or `PROTESTED`, setting `assessment_status`
        to `FINAL` and again leaving the ledger unchanged — the liability was already posted;
        finalization only makes it collectible."

        Design: Corner/endpoints/closing_a_case_is_refused_while_its_assessment_is_protested
        """
        subject = world.new_licensee("DISTRIBUTOR", legal_name="Protest Distribution Inc")
        case = world.case_at(
            subject["id"],
            "PRELIM_FINDINGS",
            "2026-08",
            "2026-08",
            selection_method="ROADSIDE_REFERRAL",
        )
        world.set_clock("2026-09-25T00:00:00Z")
        issued = world.issue_assessment(case["id"], 250000, evasion_indicator=False)
        assert_assessment_money(
            issued,
            additional_tax_cents=250000,
            assessment_penalty_cents=25000,
            assessment_interest_cents=250,
            assessed_total_cents=275250,
        )
        protested = world.protest(
            case["id"],
            subject["id"],
            "The gallons were exported and the export certificate was on file",
        )
        assert_case_dimensions(protested, "PRELIM_FINDINGS", "PROTESTED")

        response = api.advance_case(case["id"], "CLOSED", manager_headers)

        validate_error(
            response, ApiErrorId.ASSESSMENT_PENDING_DISPOSITION, expected_status=409
        )
        still = validate_success(api.get_audit_case(case["id"], manager_headers))
        assert_case_dimensions(still, "PRELIM_FINDINGS", "PROTESTED")
        assert (
            world.licensee(subject["id"])["open_audit_count"] == 1
        ), "a refused close leaves the case open"

        finalized = world.finalize(case["id"])
        assert_case_dimensions(finalized, "PRELIM_FINDINGS", "FINAL")
        closed = validate_success(api.advance_case(case["id"], "CLOSED", manager_headers))
        assert_case_dimensions(closed, "CLOSED", "FINAL")
        assert world.licensee(subject["id"])["open_audit_count"] == 0

        entries = world.ledger(subject["id"])
        assert_ledger_sequence(entries, [("ASSESSMENT", 275250)])
        assert_ledger_row(
            entries[0], "ASSESSMENT", 275250, "AuditCase", source_entity_id=case["id"]
        )
        assert_balance_matches_ledger(world.licensee(subject["id"]), entries)

    def test_closing_the_only_case_returns_the_held_claim_to_its_prior_status(
        self, api, world, manager_headers
    ):
        """The close reverts the hold it caused, and only because the count reached zero.

        PRD: "The hold is reverted by the cascade that clears its cause — licensee reactivation for
        a bond hold, and the audit case reaching `CLOSED` with the subject's `open_audit_count`
        back to zero for an audit hold — restoring `status` to `status_before_hold` and clearing
        both `status_before_hold` and `hold_reason`."
        PRD: "And no audit case for that claimant may be open — any case whose `case_status` is not
        `CLOSED` freezes new claims, and the filing fails with `ERR_REFUND_BLOCKED_BY_AUDIT` (HTTP
        422). Note the division of labour between this rule and the cascade of §3.6: an open audit
        blocks claims that have not yet been filed, while claims that already existed when the case
        opened are not denied but moved to `HELD`."

        Design: Corner/endpoints/closing_the_only_audit_case_returns_the_held_claim_to_submitted
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Hold Release Fuel Supply LLC")
        claimant = world.new_licensee("DISTRIBUTOR", legal_name="Hold Release Distribution Inc")
        world.set_clock("2026-09-05T00:00:00Z")
        world.build_return(
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
                            "date": "2026-08-13",
                        }
                    ],
                }
            ],
            file=True,
            attest_name="H. Hold",
        )
        claim = world.refund_claim(claimant["id"], "2026-08", 100.00, "OFF_ROAD")
        assert_claim_money(claim, 100.00, 3090)
        case = world.case_at(
            claimant["id"],
            "PRELIM_FINDINGS",
            "2026-08",
            "2026-08",
            selection_method="ROADSIDE_REFERRAL",
        )
        held = validate_success(api.get_refund_claim(claim["id"], world.examiner))
        assert_claim_hold(held, "OPEN_AUDIT", "SUBMITTED")
        blocked = api.create_refund_claim(
            refund_claim_payload(claimant["id"], "2026-08", 50.00, "OFF_ROAD"),
            world.examiner,
        )
        validate_error(blocked, ApiErrorId.REFUND_BLOCKED_BY_AUDIT, expected_status=422)

        response = api.advance_case(case["id"], "CLOSED", manager_headers)

        closed = validate_success(response)
        assert_case_dimensions(closed, "CLOSED", "NONE")
        assert world.licensee(claimant["id"])["open_audit_count"] == 0
        released = validate_success(api.get_refund_claim(claim["id"], world.examiner))
        assert_claim_not_held(released, "SUBMITTED")
        assert_claim_money(released, 100.00, 3090)
        _rows, refund_meta = validate_paginated(
            api.list_ledger_entries(
                claimant["id"], world.officer, params={"entry_type": "REFUND"}
            )
        )
        assert_total_count(refund_meta, 0, "REFUND entries after a released hold")


class TestInspectionDismissal:
    def test_dismissing_an_inspection_appends_a_reversal_and_restores_the_balance(
        self, api, world, supervisor_headers
    ):
        """Dismissal compensates the money and nothing else: two rows stay, the status does not move.

        PRD: "Dismissal sets `status` to `DISMISSED`, appends a `PENALTY_REVERSAL` ledger entry for
        the negative of `penalty_cents` — a compensating entry, never a deletion or mutation of the
        original `PENALTY` row — and re-derives `balance_cents` back to exactly its pre-penalty
        value, which is what keeps Invariant M exact. The licensee's `dyed_violation_count`
        decreases by one."
        PRD: "A `TaxSupervisor` may dismiss an inspection whose `status` is `PENALTY_ASSESSED`,
        supplying a `dismissal_reason`; from `RECORDED` or `DISMISSED` the request fails with
        `ERR_INSPECTION_NOT_DISMISSIBLE` (HTTP 409)."

        Design: Corner/endpoints/dismissing_an_inspection_reverses_its_penalty_without_drift
        """
        retailer = world.new_licensee(
            "RETAILER", legal_name="Reversal Retail Stops LLC", retail_channel="HIGHWAY"
        )
        assert_bond_position(retailer, required_bond_cents=400000, posted_bond_cents=0)
        inspection = world.inspection(
            retailer["id"],
            "POSITIVE",
            40.00,
            "2026-07-25",
            vehicle_identifier="MN-TRK-7300",
            location_description="US-10 westbound pullout",
        )
        assert inspection["status"] == "PENALTY_ASSESSED"
        assert_cents(inspection["penalty_cents"], 100000, "penalty_cents at assessment")

        response = api.dismiss_inspection(
            inspection["id"],
            "Laboratory retest of the sealed sample came back clear",
            supervisor_headers,
        )

        dismissed = validate_success(response)
        assert dismissed["status"] == "DISMISSED"
        assert (
            dismissed["dismissal_reason"]
            == "Laboratory retest of the sealed sample came back clear"
        )
        assert_cents(
            dismissed["penalty_cents"], 100000, "penalty_cents is history, not erased"
        )

        entries = world.ledger(retailer["id"])
        assert_ledger_sequence(
            entries, [("PENALTY", 100000), ("PENALTY_REVERSAL", -100000)]
        )
        assert_ledger_row(
            entries[0],
            "PENALTY",
            100000,
            "RoadsideInspection",
            source_entity_id=inspection["id"],
        )
        assert_ledger_row(
            entries[1],
            "PENALTY_REVERSAL",
            -100000,
            "RoadsideInspection",
            source_entity_id=inspection["id"],
        )

        after = world.licensee(retailer["id"])
        assert_cents(after["balance_cents"], 0, "balance restored to its pre-penalty value")
        assert_balance_matches_ledger(after, entries)
        assert after["dyed_violation_count"] == 0, "the violation counter decreases by one"
        assert (
            after["status"] == "PENDING_BOND"
        ), "dismissal deliberately leaves the licensee's own status alone"
        assert_bond_position(after, required_bond_cents=400000, posted_bond_cents=0)

        again = api.dismiss_inspection(
            inspection["id"], "Second thoughts about the sample", supervisor_headers
        )
        validate_error(again, ApiErrorId.INSPECTION_NOT_DISMISSIBLE, expected_status=409)
        _rows, meta = validate_paginated(
            api.list_ledger_entries(retailer["id"], world.officer)
        )
        assert_total_count(meta, 2, "the ledger after a refused second dismissal")
