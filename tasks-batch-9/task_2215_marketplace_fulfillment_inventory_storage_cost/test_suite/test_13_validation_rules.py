"""Validation breadth: the prep and case-pack rules that bind only on certain profiles, the
two appointment-window failures, per-seller SKU uniqueness, per-type evidence minimums, the
three pool overdraw codes, and the unknown line item that stops a whole receipt."""
from test_helpers import (
    ApiErrorId,
    add_line_item,
    api_client,
    confirm_plan,
    create_listing,
    create_plan,
    inbound_plan_payload,
    line_item_payload,
    lot_version,
    make_seller_operator_headers,
    read_claim,
    read_listing,
    read_lot,
    read_plan,
    read_seller,
    reimbursement_claim_payload,
    register_fulfillment_center,
    register_seller,
    removal_order_payload,
    seller_version,
    set_clock,
    setup_baseline,
    setup_lot_with_split_pools,
    ship_plan,
    sku_listing_payload,
    unfulfillable_classification_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_LINE_ITEM_ID = "88888888-8888-4888-8888-888888888888"


def _line_items(plan_id: str, headers) -> tuple:
    return validate_paginated(api_client.list_plan_line_items(plan_id, headers))


class TestPolybagPrepRequirement:
    """A polybag centre rejects an unbagged line and ignores the label it carries."""

    def _draft_plan_at_a_polybag_centre(self) -> dict:
        ctx = setup_baseline(center={"fc_code": "FC-POLY", "prep_profile": "POLYBAG_REQUIRED"})
        ctx["plan"] = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        return ctx

    def test_an_unbagged_line_is_rejected_and_writes_nothing(self):
        """The line never lands, so the plan's declaration stays at zero and its line-item
        listing stays empty.

        PRD 3.4: "When the destination centre's `prep_profile` is `POLYBAG_REQUIRED` or
        `CASE_PACK_STRICT`, every line item of the plan must have `polybagged` set to true;
        any line that does not triggers `ERR_PREP_REQUIREMENT_UNMET`."
        PRD 2.6: "10. Prep requirement — `ERR_PREP_REQUIREMENT_UNMET` (HTTP 422), enforced on
        both line-item creation and plan confirmation."

        Design: Corner/validations/polybag_prep_requirement_rejects_then_passes_once_polybagged
        """
        ctx = self._draft_plan_at_a_polybag_centre()
        response = api_client.create_line_item(
            ctx["plan"]["id"],
            line_item_payload(
                ctx["listing_id"], 100, polybagged=False,
                label_type="MANUFACTURER_BARCODE",
            ),
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_PREP_REQUIREMENT_UNMET.value, 422)

        _rows, meta = _line_items(ctx["plan"]["id"], ctx["seller_headers"])
        assert meta["total_count"] == 0
        assert read_plan(ctx["plan"]["id"], ctx["seller_id"])["declared_units"] == 0

    def test_the_same_line_passes_once_bagged_even_with_a_manufacturer_barcode(self):
        """The label rule does not bind at a polybag centre, so the only thing that had to
        change was the bag.

        PRD 3.4: "When the profile is `LABEL_ONLY` or `CASE_PACK_STRICT`, every line item
        must have `label_type` of exactly `FNSKU`; anything else triggers
        `ERR_LABEL_REQUIREMENT_UNMET`."
        PRD 3.3: "Adding a line recomputes the plan's `declared_units` as the sum of `units`
        across its line items, and re-runs the provisional allocation waterfall."

        Design: Corner/validations/polybag_prep_requirement_rejects_then_passes_once_polybagged
        """
        ctx = self._draft_plan_at_a_polybag_centre()
        response = api_client.create_line_item(
            ctx["plan"]["id"],
            line_item_payload(
                ctx["listing_id"], 100, polybagged=True,
                label_type="MANUFACTURER_BARCODE",
            ),
            ctx["seller_headers"],
        )
        line = validate_success(response, 201)
        assert line["label_type"] == "MANUFACTURER_BARCODE"
        assert line["provisional_allocated_units"] == 100

        plan = read_plan(ctx["plan"]["id"], ctx["seller_id"])
        assert plan["declared_units"] == 100
        assert plan["status"] == "DRAFT"


class TestCasePackRuleHasTwoHalves:
    """The multiple rule binds everywhere; the minimum rule only at a strict centre."""

    def _one_draft_plan_at_each_centre(self) -> dict:
        ctx = setup_baseline(quota={"base_capacity_units": 3000})
        strict = register_fulfillment_center(
            fc_code="FC-B1", region_code="US-EAST", prep_profile="CASE_PACK_STRICT",
            case_pack_min_units=12, monthly_storage_rate_cents_per_cubic_foot=91,
            ltsf_rate_cents_per_cubic_foot=640,
        )
        ctx["lenient_plan"] = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        ctx["strict_plan"] = create_plan(
            ctx["seller_id"], strict["id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        ctx["strict_fc_id"] = strict["id"]
        return ctx

    def test_units_that_are_not_a_multiple_of_the_case_pack_are_rejected_anywhere(self):
        """105 units in packs of 10 is not an exact multiple, and the label-only centre
        rejects it even though it has no case-pack minimum of its own.

        PRD 3.4: "Case packing adds a third rule: a line's `units` must be an exact positive
        multiple of its `case_pack_units`, and when the profile is `CASE_PACK_STRICT` the
        line's `case_pack_units` must additionally be at least the centre's
        `case_pack_min_units`; either failure is `ERR_CASE_PACK_VIOLATION`."

        Design: Corner/validations/case_pack_rule_binds_on_multiple_always_and_on_minimum_only_when_strict
        """
        ctx = self._one_draft_plan_at_each_centre()
        response = api_client.create_line_item(
            ctx["lenient_plan"]["id"],
            line_item_payload(ctx["listing_id"], 105, case_pack_units=10),
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_CASE_PACK_VIOLATION.value, 422)

        accepted = validate_success(
            api_client.create_line_item(
                ctx["lenient_plan"]["id"],
                line_item_payload(ctx["listing_id"], 100, case_pack_units=10),
                ctx["seller_headers"],
            ),
            201,
        )
        assert accepted["units"] == 100
        assert read_plan(ctx["lenient_plan"]["id"], ctx["seller_id"])["declared_units"] == 100

    def test_a_case_pack_below_the_centre_minimum_is_rejected_only_when_strict(self):
        """The identical 100-unit line in packs of 10 is accepted at the label-only centre and
        refused at the strict centre whose minimum is 12.

        PRD 3.1: "The payload carries a `fc_code` that must be unique across all centers, a
        `region_code` used only for reporting, a `prep_profile` drawn from
        `POLYBAG_REQUIRED`, `LABEL_ONLY` and `CASE_PACK_STRICT`, a `case_pack_min_units` of at
        least 1, a `receiving_capacity_units_per_window` of at least 1, and two integer rates
        in cents per cubic foot: `monthly_storage_rate_cents_per_cubic_foot` and
        `ltsf_rate_cents_per_cubic_foot`, both non-negative."
        PRD 3.4: "All three rules are checked twice — once when the line is added, and again
        for every line of the plan at confirmation, because the destination centre's profile
        may have changed in between."

        Design: Corner/validations/case_pack_rule_binds_on_multiple_always_and_on_minimum_only_when_strict
        """
        ctx = self._one_draft_plan_at_each_centre()
        response = api_client.create_line_item(
            ctx["strict_plan"]["id"],
            line_item_payload(ctx["listing_id"], 100, case_pack_units=10),
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_CASE_PACK_VIOLATION.value, 422)

        add_line_item(
            ctx["lenient_plan"]["id"], ctx["seller_id"], ctx["listing_id"], 100,
            case_pack_units=10,
        )
        assert read_plan(ctx["strict_plan"]["id"], ctx["seller_id"])["declared_units"] == 0
        assert read_plan(ctx["lenient_plan"]["id"], ctx["seller_id"])["declared_units"] == 100
        _rows, meta = _line_items(ctx["strict_plan"]["id"], ctx["seller_headers"])
        assert meta["total_count"] == 0


class TestAppointmentWindowSanity:
    """Two different window failures, then the window that starts exactly on the clock."""

    def _seller_and_centre_at_the_clock(self) -> dict:
        ctx = setup_baseline(with_listing=False)
        ctx["version_before"] = seller_version(ctx["seller_id"])
        return ctx

    def test_an_end_equal_to_the_start_is_an_invalid_window(self):
        """The rule is strictly-after, so a zero-length window fails on ordering rather than
        on being in the past.

        PRD 3.3: "Appointment windows are half-open — inclusive of their start, exclusive of
        their end — and are validated twice: the end must be strictly after the start, or the
        request fails with `ERR_APPOINTMENT_WINDOW_INVALID`, and the start must not be
        strictly before the logical clock's current instant, or it fails with
        `ERR_APPOINTMENT_WINDOW_IN_PAST`."

        Design: Corner/validations/appointment_window_sanity_separates_invalid_from_in_past
        """
        ctx = self._seller_and_centre_at_the_clock()
        response = api_client.create_inbound_shipment_plan(
            inbound_plan_payload(
                ctx["seller_id"], ctx["fc_id"], ctx["version_before"],
                "2026-08-10T00:00:00Z", "2026-08-10T00:00:00Z",
            ),
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_APPOINTMENT_WINDOW_INVALID.value, 422)
        assert seller_version(ctx["seller_id"]) == ctx["version_before"]

    def test_a_well_ordered_window_that_starts_before_the_clock_is_in_the_past(self):
        """One second before the clock is already too late, and the rejection leaves the
        seller's version untouched so the same guard value can be reused.

        PRD 2.10: "If `expected_seller_account_version` does not equal the seller's current
        `version`, the request is rejected with `ERR_STALE_SELLER_VERSION` (HTTP 412) and
        nothing is persisted."
        PRD 3.3: "A window starting exactly at the current instant is accepted."

        Design: Corner/validations/appointment_window_sanity_separates_invalid_from_in_past
        """
        ctx = self._seller_and_centre_at_the_clock()
        response = api_client.create_inbound_shipment_plan(
            inbound_plan_payload(
                ctx["seller_id"], ctx["fc_id"], ctx["version_before"],
                "2026-07-31T23:59:59Z", "2026-08-11T00:00:00Z",
            ),
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_APPOINTMENT_WINDOW_IN_PAST.value, 422)
        assert seller_version(ctx["seller_id"]) == ctx["version_before"]

        accepted = validate_success(
            api_client.create_inbound_shipment_plan(
                inbound_plan_payload(
                    ctx["seller_id"], ctx["fc_id"], ctx["version_before"],
                    "2026-08-01T00:00:00Z", "2026-08-11T00:00:00Z",
                ),
                ctx["seller_headers"],
            ),
            201,
        )
        assert accepted["appointment_window_start"].startswith("2026-08-01T00:00:00")
        assert accepted["status"] == "DRAFT"
        assert seller_version(ctx["seller_id"]) == ctx["version_before"] + 1


class TestSkuUniquenessIsPerSeller:
    """The same SKU string is a duplicate for one seller and a fresh listing for another."""

    def _two_sellers_one_of_them_holding_the_sku(self) -> dict:
        set_clock("2026-08-01T00:00:00Z")
        first = register_seller()
        second = register_seller(
            legal_name="Southgate Supply", storage_cubic_feet_entitlement=500.0000,
            unit_cost_cap_cents=150000,
        )
        return {
            "first_id": first["id"],
            "second_id": second["id"],
            "listing": create_listing(first["id"], sku="SKU-ALPHA"),
        }

    def test_the_same_seller_cannot_register_the_sku_twice(self):
        """The duplicate is refused and the stored listing keeps its original numbers rather
        than absorbing the rejected body.

        PRD 3.2: "The pair of owning seller and `sku` must be unique: a second listing with
        the same `sku` under the same seller is rejected with `ERR_DUPLICATE_SKU`."
        PRD 2.6: "15. Structural constraints: a plan being confirmed has at least one line item
        (`ERR_PLAN_HAS_NO_LINE_ITEMS`, HTTP 422); a seller's SKU is unique
        (`ERR_DUPLICATE_SKU`, HTTP 409); a requested removal window does not collide with
        another requested removal window on the same lot (`ERR_REMOVAL_WINDOW_CONFLICT`, HTTP
        409); and a claim has not exhausted its two resubmissions
        (`ERR_RESUBMISSION_LIMIT_REACHED`, HTTP 422)."

        Design: Corner/validations/sku_uniqueness_is_scoped_per_seller_not_global
        """
        ctx = self._two_sellers_one_of_them_holding_the_sku()
        response = api_client.create_sku_listing(
            sku_listing_payload(
                ctx["first_id"], sku="SKU-ALPHA", unit_cubic_feet=2.0000,
                unit_cost_cents=9999,
            ),
            make_seller_operator_headers(ctx["first_id"]),
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_SKU.value, 409)

        stored = read_listing(ctx["listing"]["id"], ctx["first_id"])
        assert stored["unit_cubic_feet"] == 1.0000
        assert stored["unit_cost_cents"] == 1250

    def test_a_second_seller_may_register_the_same_sku_string(self):
        """Uniqueness is scoped to the owning seller, so both accounts end up holding exactly
        one listing named SKU-ALPHA.

        PRD 3.2: "A `SellerOperator` creates a listing by supplying the owning
        `seller_account_id`, a `sku`, a positive `unit_cubic_feet` carried to four decimals,
        and a non-negative `unit_cost_cents` that later drives both liquidation recovery and
        reimbursement valuation."
        PRD 2.6: "6. Ownership scope: a `SellerOperator` acting outside its own seller chain is
        rejected with `ERR_SELLER_SCOPE_VIOLATION`; an `FcOperator` receiving a plan bound
        elsewhere or completing a removal on a lot held elsewhere is rejected with
        `ERR_FC_SCOPE_VIOLATION`."

        Design: Corner/validations/sku_uniqueness_is_scoped_per_seller_not_global
        """
        ctx = self._two_sellers_one_of_them_holding_the_sku()
        second_listing = validate_success(
            api_client.create_sku_listing(
                sku_listing_payload(
                    ctx["second_id"], sku="SKU-ALPHA", unit_cubic_feet=3.0000,
                    unit_cost_cents=777,
                ),
                make_seller_operator_headers(ctx["second_id"]),
            ),
            201,
        )
        assert second_listing["sku"] == "SKU-ALPHA"
        assert second_listing["seller_account_id"] == ctx["second_id"]

        for seller_id in (ctx["first_id"], ctx["second_id"]):
            _rows, meta = validate_paginated(
                api_client.list_seller_sku_listings(
                    seller_id, make_seller_operator_headers(seller_id)
                )
            )
            assert meta["total_count"] == 1


class TestEvidenceMinimumIsPerClaimType:
    """Two documents are enough for an inbound loss but not for warehouse damage."""

    def _a_lot_with_twenty_damaged_units(self) -> dict:
        return setup_lot_with_split_pools(60, 20)

    def test_two_documents_are_below_the_warehouse_damage_minimum(self):
        """The claim is refused before it exists, so the lot's claim list stays empty and its
        reconciliation dimension never moves.

        PRD 3.8: "`DAMAGED_WAREHOUSE` draws on the lot's `unfulfillable_units`, anchors on
        `unfulfillable_recorded_at`, and requires at least 3."
        PRD 3.8: "An `evidence_document_count` below the minimum for the claim's type is
        rejected with `ERR_EVIDENCE_REFERENCE_MISSING`, and a `claimed_units` figure exceeding
        the claim type's pool on the lot at submission time is rejected with
        `ERR_REIMBURSEMENT_EXCEEDS_ELIGIBLE_UNITS`."

        Design: Corner/validations/evidence_minimum_per_claim_type_rejects_then_accepts
        """
        ctx = self._a_lot_with_twenty_damaged_units()
        response = api_client.file_reimbursement_claim(
            reimbursement_claim_payload(
                ctx["lot_id"], "DAMAGED_WAREHOUSE", 5, 2, "EV-2"
            ),
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_EVIDENCE_REFERENCE_MISSING.value, 422)

        _rows, meta = validate_paginated(
            api_client.list_lot_reimbursement_claims(ctx["lot_id"], ctx["seller_headers"])
        )
        assert meta["total_count"] == 0
        assert read_lot(ctx["lot_id"], ctx["seller_id"])["reconciliation_status"] == (
            "RECONCILED"
        )

    def test_the_third_document_makes_the_identical_claim_acceptable(self):
        """Only the document count changed, and the claim now opens SUBMITTED with its
        deadline sixty days after the damage was recorded.

        PRD 3.8: "The seller answers by resubmitting with a fresh `evidence_document_count`
        and `evidence_reference`, which overwrite the stored values and must again clear the
        type's evidence minimum."
        PRD 3.8: "Filing pins `filing_deadline_at` to the selected anchor plus 60 days, and
        the claim opens at `status` of `SUBMITTED` with `resubmission_count` of 0,
        `eligible_units`, `approved_units` and `reimbursement_amount_cents` all at 0, and
        `decided_at` null."

        Design: Corner/validations/evidence_minimum_per_claim_type_rejects_then_accepts
        """
        ctx = self._a_lot_with_twenty_damaged_units()
        api_client.file_reimbursement_claim(
            reimbursement_claim_payload(
                ctx["lot_id"], "DAMAGED_WAREHOUSE", 5, 2, "EV-2"
            ),
            ctx["seller_headers"],
        )
        accepted = validate_success(
            api_client.file_reimbursement_claim(
                reimbursement_claim_payload(
                    ctx["lot_id"], "DAMAGED_WAREHOUSE", 5, 3, "EV-3"
                ),
                ctx["seller_headers"],
            ),
            201,
        )
        assert accepted["status"] == "SUBMITTED"

        stored = read_claim(accepted["id"])
        assert stored["evidence_document_count"] == 3
        assert stored["filing_deadline_at"].startswith("2026-09-30T00:00:00")

        _rows, meta = validate_paginated(
            api_client.list_lot_reimbursement_claims(ctx["lot_id"], ctx["seller_headers"])
        )
        assert meta["total_count"] == 1
        assert read_lot(ctx["lot_id"], ctx["seller_id"])["reconciliation_status"] == (
            "RECONCILED"
        )


class TestPoolOverdrawsSplitIntoTwoCodes:
    """The same 60/20 lot answers three overdraws with two different identifiers."""

    def _a_lot_with_sixty_and_twenty(self) -> dict:
        ctx = setup_lot_with_split_pools(60, 20)
        ctx["version_before"] = lot_version(ctx["lot_id"], ctx["seller_id"])
        return ctx

    def test_removal_and_classification_overdraws_share_the_pool_code(self):
        """One more unit than the pool holds is refused on both the seller's removal request
        and the centre's classification.

        PRD 3.6: "The requested count must not exceed the named source pool on the lot, or
        the request is rejected with `ERR_INSUFFICIENT_POOL_UNITS`."
        PRD 3.6: "A classification whose `units` exceeds the lot's current
        `fulfillable_units` is rejected with `ERR_INSUFFICIENT_POOL_UNITS`."

        Design: Corner/validations/pool_availability_rules_separate_removal_classification_and_claim_overdraws
        """
        ctx = self._a_lot_with_sixty_and_twenty()
        validate_error(
            api_client.create_removal_order(
                removal_order_payload(
                    ctx["lot_id"], ctx["version_before"], 61,
                    removal_method="DISPOSAL", unit_pool="FULFILLABLE",
                ),
                ctx["seller_headers"],
            ),
            ApiErrorId.ERR_INSUFFICIENT_POOL_UNITS.value, 422,
        )
        validate_error(
            api_client.classify_unfulfillable(
                ctx["lot_id"],
                unfulfillable_classification_payload(61, "CUSTOMER_DAMAGE"),
                ctx["fc_headers"],
            ),
            ApiErrorId.ERR_INSUFFICIENT_POOL_UNITS.value, 422,
        )

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["fulfillable_units"] == 60
        assert lot["unfulfillable_units"] == 20
        assert lot["units_reserved_for_removal"] == 0
        assert lot["version"] == ctx["version_before"]

        _rows, meta = validate_paginated(
            api_client.list_lot_removal_orders(ctx["lot_id"], ctx["seller_headers"])
        )
        assert meta["total_count"] == 0

    def test_a_claim_beyond_the_eligible_pool_gets_its_own_code(self):
        """25 claimed units against a 20-unit damaged pool is a reimbursement overdraw, not a
        pool overdraw, and it leaves the pools alone.

        PRD 3.8: "The `claim_type` selects three things at once: the eligible unit pool on
        the lot, the deadline anchor, and the evidence minimum."
        PRD 2.6: "17. Unit availability, all HTTP 422: `ERR_INSUFFICIENT_POOL_UNITS` on
        removal-order creation and on unfulfillable classification,
        `ERR_REIMBURSEMENT_EXCEEDS_ELIGIBLE_UNITS` on claim filing, and
        `ERR_NO_FULFILLABLE_INVENTORY` on multi-channel order placement."

        Design: Corner/validations/pool_availability_rules_separate_removal_classification_and_claim_overdraws
        """
        ctx = self._a_lot_with_sixty_and_twenty()
        validate_error(
            api_client.file_reimbursement_claim(
                reimbursement_claim_payload(
                    ctx["lot_id"], "DAMAGED_WAREHOUSE", 25, 3, "EV-25"
                ),
                ctx["seller_headers"],
            ),
            ApiErrorId.ERR_REIMBURSEMENT_EXCEEDS_ELIGIBLE_UNITS.value, 422,
        )

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["fulfillable_units"] == 60
        assert lot["unfulfillable_units"] == 20
        assert lot["version"] == ctx["version_before"]


class TestUnknownLineItemStopsTheWholeReceipt:
    """One bad identifier in the array and the valid sibling line is not credited either."""

    def test_the_receipt_is_not_found_before_any_unit_is_applied(self):
        """The 100-unit line named alongside the unknown identifier stays at zero received,
        the plan stays in transit and no lot is ever created.

        PRD 3.5: "Every referenced line item must belong to the plan being received, or the
        whole call fails with `ERR_LINE_ITEM_NOT_FOUND`."
        PRD 2.5: "Inside a receipt payload, a `shipment_line_item_id` that does not resolve — or
        that resolves to a line item belonging to a different plan than the one being received —
        yields `ERR_LINE_ITEM_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/unknown_shipment_line_item_in_receive_payload_not_found_before_state_work
        """
        ctx = setup_baseline()
        second_listing = create_listing(ctx["seller_id"], sku="SKU-BETA")
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
        )
        alpha_line = add_line_item(plan["id"], ctx["seller_id"], ctx["listing_id"], 100)
        add_line_item(plan["id"], ctx["seller_id"], second_listing["id"], 50)
        confirm_plan(plan["id"], ctx["seller_id"])
        ship_plan(plan["id"], ctx["seller_id"], carrier_reference="CR-13")

        response = api_client.receive_plan(
            plan["id"],
            {
                "received_lines": [
                    {
                        "shipment_line_item_id": alpha_line["id"],
                        "received_units": 100,
                        "unfulfillable_units": 0,
                    },
                    {
                        "shipment_line_item_id": UNKNOWN_LINE_ITEM_ID,
                        "received_units": 50,
                        "unfulfillable_units": 0,
                    },
                ]
            },
            ctx["fc_headers"],
        )
        validate_error(response, ApiErrorId.ERR_LINE_ITEM_NOT_FOUND.value, 404)

        stored_plan = read_plan(plan["id"], ctx["seller_id"])
        assert stored_plan["status"] == "IN_TRANSIT"
        assert stored_plan["received_units"] == 0

        for line in _line_items(plan["id"], ctx["seller_headers"])[0]:
            assert line["received_units"] == 0

        _lots, meta = validate_paginated(
            api_client.list_inventory_lots(
                ctx["seller_headers"], params={"sku_listing_id": ctx["listing_id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_listing(ctx["listing_id"], ctx["seller_id"])["lot_ever_created"] is False
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 150
