"""Derived-figure coverage: barcode check digits, automatic bin selection, the auction
commission ladder, owner-notice deadlines, transfer window limits and the risk index."""

from test_helpers import (
    add_general_bin,
    adjudicate_case,
    assert_two_decimal_exactness,
    authorize_order,
    charge_case,
    custody_transfer_payload,
    evidence_item_payload,
    execute_order,
    log_and_store_item,
    log_item,
    open_order,
    owner_claim_payload,
    read_custodian,
    read_item,
    read_location,
    read_room,
    resolve_discrepancy,
    scan_barcode,
    schedule_audit,
    set_clock,
    settle_payload,
    setup_corner_base,
    setup_second_room,
    start_audit,
    storage_assignment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _log_general_item(api, case_id: str, headers: dict, item_description: str) -> dict:
    """Log one plain GENERAL item, asserting the 201 PRD section 4 requires at intake."""
    return validate_success(
        api.create_evidence_item(
            evidence_item_payload(
                case_id,
                item_description=item_description,
                category="GENERAL",
                packaging_type="PAPER_BAG",
                appraised_value_cents=100,
                seized_at="2026-07-31T12:00:00Z",
            ),
            headers,
        ),
        201,
    )


class TestBarcodeAssignment:
    """Item sequence and check digit are derived per case from the printed prefix."""

    def test_sequence_is_scoped_to_the_case_and_the_check_digit_follows_the_digits(self, api):
        """Three items in one case number 1, 2, 3, and the check digit tracks every digit.

        PRD 3.2: "First the service computes `item_sequence` as one more than the number of
        evidence items already recorded against the same `case_id`; disposed items are
        counted, so a sequence number is never reused within a case."
        PRD 3.2: "It then forms a working string by concatenating the room's
        `agency_code`, the case's `case_number`, and `item_sequence` zero-padded to four
        characters."
        PRD 3.2: "Taking the decimal digits of that working string in left-to-right order
        and ignoring any non-digit character, it weights the rightmost digit by 3, the
        next digit leftward by 1, and continues alternating those two weights leftward
        across all digits; the weighted digits are summed."
        PRD 3.2: "The check digit is ten minus the remainder of that sum divided by ten,
        itself reduced modulo ten (so a sum ending in zero produces a check digit of
        zero)."
        PRD 3.2: "The stored `barcode` is then the `agency_code`, a hyphen, the
        `case_number`, a hyphen, the four-character zero-padded `item_sequence`, a hyphen,
        and the check digit."
        PRD 3.2: "For agency `CPD`, case `26-00001` and sequence 1, the barcode is
        `CPD-26-00001-0001-2`."
        PRD 3.2: "Barcodes are unique across all evidence items."

        Design: Corner/calculations/barcode_check_digit_sequence_within_case
        """
        env = setup_corner_base()
        second = setup_second_room(env)

        first = _log_general_item(api, env["case1_id"], env["tech_headers"], "Sequence one")
        secondary = _log_general_item(
            api, env["case1_id"], env["tech_headers"], "Sequence two"
        )
        third = _log_general_item(
            api, env["case1_id"], env["tech_headers"], "Sequence three"
        )
        foreign = _log_general_item(
            api, second["case_id"], second["tech_headers"], "Other agency item"
        )

        # Weighted sum 18 over the digits 2 6 0 0 0 0 1 0 0 0 1, check digit (10 - 8) % 10.
        assert first["barcode"] == "CPD-26-00001-0001-2"
        # Weighted sum 21, then 24.
        assert secondary["barcode"] == "CPD-26-00001-0002-9"
        assert third["barcode"] == "CPD-26-00001-0003-6"
        assert first["item_sequence"] == 1
        assert secondary["item_sequence"] == 2
        assert third["item_sequence"] == 3

        # The sequence restarts per case, but the agency code and case number digits feed
        # the weighted sum, so the same 0001 earns a different check digit.
        assert foreign["barcode"] == "MPD-26-90001-0001-5"
        assert foreign["item_sequence"] == 1

        barcodes = [
            first["barcode"], secondary["barcode"], third["barcode"], foreign["barcode"],
        ]
        assert len(set(barcodes)) == 4
        for barcode in barcodes:
            check_digit = barcode.rsplit("-", 1)[1]
            assert len(check_digit) == 1
            assert check_digit.isdigit() is True


class TestStorageAutoSelection:
    """Omitting the bin makes the service fill the tightest usable bin first."""

    def test_the_bin_with_fewest_free_slots_fills_before_the_roomier_one(self, api):
        """The one-slot bin wins on free-slot ranking, then drops out and the overflow lands next door.

        PRD 3.3: "When `storage_location_id` is omitted, the service selects the tightest
        fitting bin."
        PRD 3.3: "The eligible pool is every storage location whose `property_room_id`
        matches the room of the item's case, whose `status` is `OPEN`, whose `category`
        equals the item's `required_storage_category`, whose `occupied_slots` is strictly
        less than its `capacity_slots`, and — for refrigerated locations only — whose
        `temperature_c` is at most 4.0."
        PRD 3.3: "Candidates are ranked by the number of free slots, computed as
        `capacity_slots` minus `occupied_slots`, in ascending order so that the fullest
        usable bin wins; ties are broken by `capacity_slots` ascending, and any remaining
        tie by `created_at` ascending."
        PRD 3.3: "The resource's `id` is never a decision input."

        Design: Corner/calculations/storage_autoselect_picks_tightest_fit_location
        """
        env = setup_corner_base()
        item_one = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Autoselect item one",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=1000,
            seized_at="2026-07-31T12:00:00Z",
        )
        item_two = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Autoselect item two",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=1000,
            seized_at="2026-07-31T12:05:00Z",
        )

        first_choice = validate_success(
            api.assign_storage(
                item_one["id"], storage_assignment_payload(), env["tech_headers"]
            ),
            200,
        )
        second_choice = validate_success(
            api.assign_storage(
                item_two["id"], storage_assignment_payload(), env["tech_headers"]
            ),
            200,
        )

        # G-09 offers 1 free slot against G-01's 2, so it is the tighter fit even though
        # it was created later.
        assert first_choice["storage_location_id"] == env["loc_g9_id"]
        assert first_choice["custody_state"] == "STORED"
        assert second_choice["storage_location_id"] == env["loc_g_id"]
        assert second_choice["custody_state"] == "STORED"

        tight = read_location(env, env["loc_g9_id"])
        assert tight["capacity_slots"] == 1
        assert tight["occupied_slots"] == 1
        roomy = read_location(env, env["loc_g_id"])
        assert roomy["capacity_slots"] == 2
        assert roomy["occupied_slots"] == 1


class TestAuctionCommissionTierBoundary:
    """The commission ladder's first boundary at 50000 cents is an inclusive upper bound."""

    def test_selling_one_cent_above_the_tier_edge_lowers_the_commission(self, api):
        """A gross of exactly 50000 takes fifteen percent; 50001 drops to ten percent.

        PRD 2.8: "Tiered rate boundaries are inclusive upper bounds."
        PRD 3.7: "**Step one** determines the auctioneer's commission from the hammer
        price using an inclusive-upper-bound tier ladder: a gross of 50000 cents or less
        attracts fifteen percent (a rate of 0.15), a gross above that but not exceeding
        500000 cents attracts ten percent (0.10), and anything above 500000 cents attracts
        seven percent (0.07)."
        PRD 3.7: "**Step two** takes the subtotal as the gross less `commission_cents`."
        PRD 3.7: "**Step three** computes the cap on storage-cost recovery as thirty
        percent (a rate of 0.30) of that post-commission subtotal, floored to whole cents
        — the cap is a share of the subtotal, not of the gross and not of the final net."
        PRD 3.7: "**Step four** computes the raw recovery and applies the cap: the number
        of storage days is the whole number of days, rounded down, between the item's
        `intake_at` and the order's `executed_at`, and the raw recovery is that day count
        multiplied by the daily rate for the item's `required_storage_category`, which is
        25 cents per day for `GENERAL`, 120 cents per day for `REFRIGERATED`, 60 cents per
        day for `HIGH_VALUE_VAULT` and 200 cents per day for `OVERSIZED_YARD`; the
        `storage_recovery_cents` actually charged is the lesser of the raw recovery and
        the cap."
        PRD 3.7: "**Step five** sets `settled_net_proceeds_cents` to the subtotal less
        `storage_recovery_cents`."
        PRD 3.7: "For an auction, the estimate is the item's `appraised_value_cents` less
        a flat ten percent commission on that appraisal, the commission being the
        appraised value multiplied by 0.10 and rounded half up to whole cents."
        PRD 3.7: "Settlement then moves the order `EXECUTED → SETTLED`, stamps
        `settled_at`, sets `settlement_status` to `HELD`, and increases the room's
        `escrow_balance_cents` by `settled_net_proceeds_cents`."

        Design: Corner/calculations/settled_commission_tier_boundary_at_fifty_thousand
        """
        env = setup_corner_base()
        item_a = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Auction lot at the tier edge",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=40000,
            seized_at="2026-07-30T09:00:00Z",
        )
        item_b = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Auction lot one cent above the edge",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=60000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_case(env, env["case2_id"])
        # The FINAL variant floors at intake plus 90 whole days, that is 2026-10-30, so
        # execution there gives exactly 90 storage days at the GENERAL rate of 25 cents.
        set_clock("2026-10-30T00:00:00Z")
        adjudicate_case(env, env["case2_id"])
        order_a = open_order(env, item_a["id"], "AUCTION", reserve_price_cents=10000)
        order_b = open_order(env, item_b["id"], "AUCTION", reserve_price_cents=10000)
        authorize_order(env, order_a["id"], "CO-2026-0101")
        authorize_order(env, order_b["id"], "CO-2026-0102")
        execute_order(env, order_a["id"], env["tech2_id"], env["aud_id"])
        execute_order(env, order_b["id"], env["tech2_id"], env["aud_id"])

        settled_a = validate_success(
            api.settle_order(order_a["id"], settle_payload(50000), env["manager"]), 200
        )
        settled_b = validate_success(
            api.settle_order(order_b["id"], settle_payload(50001), env["manager"]), 200
        )

        # 50000 * 0.15 = 7500; subtotal 42500; cap floor(42500 * 0.30) = 12750; raw
        # recovery 90 * 25 = 2250, which is the lesser.
        assert settled_a["commission_cents"] == 7500
        assert settled_a["storage_recovery_cents"] == 2250
        assert settled_a["settled_net_proceeds_cents"] == 40250
        assert settled_a["status"] == "SETTLED"
        assert settled_a["settlement_status"] == "HELD"

        # 50001 * 0.10 = 5000.1, rounded half up to 5000; subtotal 45001.
        assert settled_b["commission_cents"] == 5000
        assert settled_b["storage_recovery_cents"] == 2250
        assert settled_b["settled_net_proceeds_cents"] == 42751
        assert settled_b["status"] == "SETTLED"
        assert settled_b["settlement_status"] == "HELD"

        # Selling one cent more yields 2500 cents less commission and 2501 more net,
        # which is only correct if the tier test is the inclusive form.
        assert settled_b["commission_cents"] - settled_a["commission_cents"] == -2500
        assert (
            settled_b["settled_net_proceeds_cents"]
            - settled_a["settled_net_proceeds_cents"]
        ) == 2501

        # Both estimates were computed from the appraisal, not from the hammer price.
        assert order_a["estimated_net_proceeds_cents"] == 36000
        assert order_b["estimated_net_proceeds_cents"] == 54000

        room = read_room(env)
        assert room["escrow_balance_cents"] == 83001


class TestOwnerClaimDeadline:
    """The notice window is a base period per property kind plus a publication extension."""

    def test_publication_adds_fifteen_days_on_top_of_the_base_notice_period(self, api):
        """Found property earns 90 days, seized property 30, and publication adds 15 more.

        PRD 3.6: "The claim opens with `status` of `NOTICE_SENT`, `notified_at` stamped
        from the logical clock, and `proof_document_ref` and `verified_at` null, and a
        chain entry with `event_type` of `NOTICE_SENT` is appended to the item."
        PRD 3.6: "The base period is 90 days when the item's `is_found_property` flag is
        true, and 30 days otherwise."
        PRD 3.6: "Publication earns a further 15 days on top, because a notice in a
        newspaper reaches a claimant more slowly than a certified letter or a
        conversation; `CERTIFIED_MAIL` and `IN_PERSON` add nothing."
        PRD 3.6: "The deadline is `notified_at` plus the sum of the base period and the
        extension, added as whole days."
        PRD 2.8: "Retention periods and notice periods are expressed in whole days and are
        added to a UTC instant as exact increments of 86,400 seconds."

        Design: Corner/calculations/owner_claim_deadline_publication_extends_window
        """
        env = setup_corner_base()
        found_published = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Found bicycle for publication notice",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=30000,
            seized_at="2026-07-31T12:00:00Z",
            is_found_property=True,
        )
        found_mailed = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Found wallet for mailed notice",
            category="GENERAL",
            packaging_type="SEALED_ENVELOPE",
            appraised_value_cents=5000,
            seized_at="2026-07-31T12:00:00Z",
            is_found_property=True,
        )
        seized = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Seized toolbox",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=8000,
            seized_at="2026-07-31T12:00:00Z",
        )
        assert found_published["is_found_property"] is True
        assert found_mailed["is_found_property"] is True
        assert seized["is_found_property"] is False
        set_clock("2026-08-05T00:00:00Z")

        published_claim = validate_success(
            api.create_owner_claim(
                owner_claim_payload(
                    found_published["id"],
                    claimant_name="Unknown owner",
                    claimant_contact="Legal notices page 4",
                    notice_method="PUBLICATION",
                ),
                env["tech_headers"],
            ),
            201,
        )
        mailed_claim = validate_success(
            api.create_owner_claim(
                owner_claim_payload(
                    found_mailed["id"],
                    claimant_name="Dana Vale",
                    claimant_contact="12 Fern Street",
                    notice_method="CERTIFIED_MAIL",
                ),
                env["tech_headers"],
            ),
            201,
        )
        seized_claim = validate_success(
            api.create_owner_claim(
                owner_claim_payload(
                    seized["id"],
                    claimant_name="Omar Beck",
                    claimant_contact="88 Grove Road",
                    notice_method="IN_PERSON",
                ),
                env["tech_headers"],
            ),
            201,
        )

        assert published_claim["notified_at"] == "2026-08-05T00:00:00.000Z"
        # 90 found-property days plus the 15-day publication extension is 105 days.
        assert published_claim["claim_deadline_at"] == "2026-11-18T00:00:00.000Z"
        # The same found-property base with certified mail earns nothing extra.
        assert mailed_claim["claim_deadline_at"] == "2026-11-03T00:00:00.000Z"
        # is_found_property defaulted to false, so the base period is 30 days.
        assert seized_claim["claim_deadline_at"] == "2026-09-04T00:00:00.000Z"

        for claim in (published_claim, mailed_claim, seized_claim):
            assert claim["status"] == "NOTICE_SENT"
            assert claim["proof_document_ref"] is None
            assert claim["verified_at"] is None


class TestTransferWindowLimits:
    """The maximum custody window is set by the transfer's purpose, inclusively."""

    def test_a_window_one_millisecond_past_the_purpose_maximum_is_refused(self, api):
        """Exactly 30 days of laboratory analysis is accepted; a millisecond more is not.

        PRD 3.5: "The elapsed span between the two instants must not exceed the maximum
        for the purpose: 30 days for `LAB_ANALYSIS`, 3 days for `COURT_PRESENTATION`, and
        7 days for `INVESTIGATIVE_REVIEW`."
        PRD 3.5: "A window of exactly the maximum is permitted; one millisecond longer is
        refused with `ERR_TRANSFER_WINDOW_TOO_LONG`."
        PRD 3.5: "The new row starts with `status` of `REQUESTED`, with
        `from_custodian_id`, all three signature fields, `returned_at` and
        `denial_reason` null, and it increments both the receiving custodian's
        `open_escort_count` and the item's `open_transfer_count`."

        Design: Corner/calculations/transfer_window_exceeding_purpose_limit_rejected
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Tool mark standard",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=2000,
            seized_at="2026-07-31T12:00:00Z",
        )

        validate_error(
            api.create_custody_transfer(
                custody_transfer_payload(
                    item["id"], env["lab_id"], "LAB_ANALYSIS",
                    "2026-08-02T09:00:00Z", "2026-09-01T09:00:00.001Z",
                ),
                env["lab_headers"],
            ),
            "ERR_TRANSFER_WINDOW_TOO_LONG",
            422,
        )
        # Four days of court presentation exceeds that purpose's three-day maximum, so the
        # limit is per purpose rather than global.
        validate_error(
            api.create_custody_transfer(
                custody_transfer_payload(
                    item["id"], env["inv_id"], "COURT_PRESENTATION",
                    "2026-08-02T09:00:00Z", "2026-08-06T09:00:00Z",
                ),
                env["inv_headers"],
            ),
            "ERR_TRANSFER_WINDOW_TOO_LONG",
            422,
        )

        accepted = validate_success(
            api.create_custody_transfer(
                custody_transfer_payload(
                    item["id"], env["lab_id"], "LAB_ANALYSIS",
                    "2026-08-02T09:00:00Z", "2026-09-01T09:00:00Z",
                ),
                env["lab_headers"],
            ),
            201,
        )
        assert accepted["status"] == "REQUESTED"

        rows, meta = validate_paginated(
            api.list_custody_transfers(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == accepted["id"]
        # The two refused attempts left no counter residue.
        assert read_item(env, item["id"])["open_transfer_count"] == 1
        assert read_custodian(env, env["lab_id"])["open_escort_count"] == 1


class TestAuditRiskIndexInputSet:
    """The risk index is re-derived from the discrepancies still in the open set."""

    def test_resolving_one_discrepancy_re_derives_the_index_from_the_survivors(self, api):
        """A resolved discrepancy leaves the input set; the surviving row keeps its own weight.

        PRD 3.8: "If the scanned item's `storage_location_id` is not the audited location,
        the item is physically present in the wrong place, and a discrepancy is raised on
        the spot with `kind` of `MISPLACED` and `status` of `OPEN`, incrementing the
        room's `open_discrepancy_count` and triggering a `posture` recomputation."
        PRD 3.8: "The kind weight is 5.0 for a `MISSING` discrepancy and 2.0 for a
        `MISPLACED` one."
        PRD 3.8: "The value multiplier is one plus the lesser of two quantities: the
        item's `appraised_value_cents` divided by 1000000 — that is, its value expressed
        in units of ten thousand dollars — and a ceiling of 2.0, so that no single item
        can contribute a value multiplier above 3.0."
        PRD 3.8: "The category multiplier is 1.5 when the audited location's `category` is
        `HIGH_VALUE_VAULT` or `REFRIGERATED`, and 1.0 for `GENERAL` and `OVERSIZED_YARD`."
        PRD 3.8: "The product of the three is rounded half up to two decimal places and
        stored on the discrepancy as `weight_contribution`."
        PRD 3.8: "The session's `risk_index` is then the sum of those already-rounded
        contributions, itself rounded half up to two decimal places."
        PRD 3.8: "Resolved discrepancies drop out of the calculation entirely, and the
        index is re-derived whenever one of the session's discrepancies is resolved."
        PRD 3.8: "Resolving a `MISPLACED` discrepancy as `FOUND` instead relocates the
        item into the audited location: it requires that location to have
        `occupied_slots` strictly below `capacity_slots` (`ERR_STORAGE_LOCATION_FULL`) and
        its `category` to equal the item's `required_storage_category`
        (`ERR_STORAGE_CATEGORY_MISMATCH`), and on success the item's
        `storage_location_id` becomes the audited location while the old location's
        `occupied_slots` is decremented by 1 and the new location's incremented by 1."

        Design: Corner/calculations/risk_index_recomputed_when_discrepancy_resolves_out_of_input_set
        """
        env = setup_corner_base()
        add_general_bin(env, "G-02", 4)
        item_x = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g2_id"],
            item_description="Misplaced camera",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=300000,
            seized_at="2026-07-31T12:00:00Z",
        )
        item_y = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g2_id"],
            item_description="Misplaced laptop",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=400000,
            seized_at="2026-07-31T12:05:00Z",
        )
        # The audited bin G-09 is empty, so nothing can be expected and never scanned.
        audited = read_location(env, env["loc_g9_id"])
        session = schedule_audit(
            env, env["loc_g9_id"], audited["version"],
            "2026-08-10T09:00:00Z", "2026-08-10T17:00:00Z",
        )
        start_audit(env, session["id"])
        scan_barcode(env, session["id"], item_x["barcode"])
        scan_barcode(env, session["id"], item_y["barcode"])

        reconciled = validate_success(
            api.reconcile_audit_session(session["id"], env["aud_headers"]), 200
        )
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["missing_count"] == 0
        assert reconciled["misplaced_count"] == 2
        assert_two_decimal_exactness(reconciled["risk_index"])
        assert float(reconciled["risk_index"]) == 5.40

        rows, meta = validate_paginated(
            api.list_discrepancies(
                env["manager"], params={"audit_session_id": session["id"]}
            )
        )
        assert meta["total_count"] == 2
        discrepancy_x = [
            row for row in rows if row["evidence_item_id"] == item_x["id"]
        ][0]
        discrepancy_y = [
            row for row in rows if row["evidence_item_id"] == item_y["id"]
        ][0]
        assert discrepancy_x["kind"] == "MISPLACED"
        assert discrepancy_y["kind"] == "MISPLACED"
        # 2.0 * (1 + 300000 / 1000000) * 1.0, the audited bin being GENERAL.
        assert float(discrepancy_x["weight_contribution"]) == 2.60
        assert float(discrepancy_y["weight_contribution"]) == 2.80

        resolve_discrepancy(
            env, discrepancy_x["id"], "FOUND",
            "Camera relocated into the audited bin G-09",
        )

        after = validate_success(
            api.get_audit_session(session["id"], env["aud_headers"]), 200
        )
        assert_two_decimal_exactness(after["risk_index"])
        # Re-derived from the survivors, not decremented blindly.
        assert float(after["risk_index"]) == 2.80

        surviving = validate_success(
            api.get_discrepancy(discrepancy_y["id"], env["manager"]), 200
        )
        assert surviving["status"] == "OPEN"
        # Filtering changes the input set, not the per-row weights.
        assert float(surviving["weight_contribution"]) == 2.80

        assert read_item(env, item_x["id"])["storage_location_id"] == env["loc_g9_id"]

        room = read_room(env)
        assert room["open_discrepancy_count"] == 1
        assert room["posture"] == "RESTRICTED"
