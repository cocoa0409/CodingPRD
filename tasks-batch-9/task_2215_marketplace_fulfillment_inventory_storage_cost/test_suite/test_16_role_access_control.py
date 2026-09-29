"""Role breadth: four exclusive write families each refusing the other three roles, the reads
and the PATCH that are shared per-endpoint rather than per-entity, peer isolation by scope
rather than by role, and the segregation of duties between filer and adjudicator."""
from test_helpers import (
    ADJUDICATOR,
    ADMIN,
    ApiErrorId,
    api_client,
    create_in_transit_plan,
    create_listing,
    decide_claim,
    file_claim,
    get_success_data,
    inbound_plan_payload,
    make_fc_operator_headers,
    make_seller_operator_headers,
    open_quota,
    read_claim,
    read_fulfillment_center,
    read_listing,
    read_lot,
    read_plan,
    read_seller,
    receive_plan,
    register_fulfillment_center,
    register_seller,
    reimbursement_claim_payload,
    seller_payload,
    seller_version,
    set_clock,
    set_receiving_posture,
    setup_baseline,
    setup_lot_with_split_pools,
    setup_received_lot,
    sku_listing_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestExclusiveWriteFamilies:
    """Onboarding, plan drafting, receiving and listing creation each belong to one role."""

    def _in_transit_plan_of_sixty(self) -> dict:
        ctx = setup_baseline()
        built = create_in_transit_plan(
            ctx["seller_id"], ctx["fc_id"], ctx["listing_id"], 60,
            "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z",
        )
        ctx["plan"] = built["plan"]
        ctx["line_item"] = built["line_item"]
        # Read the seller's `version` once the whole setup has landed: PRD 2.10 says a
        # successful plan creation increments it and PRD 2.4 says every mutation does, so
        # the refused writes below must be measured against the post-setup value — and
        # that same value is the guard the refused plan creation quotes.
        ctx["seller_version_before"] = seller_version(ctx["seller_id"])
        return ctx

    def _four_cross_role_writes(self, ctx: dict) -> list:
        return [
            api_client.create_seller(
                seller_payload(
                    legal_name="Self Onboarded", storage_cubic_feet_entitlement=10.0000,
                    unit_cost_cap_cents=100,
                ),
                ctx["seller_headers"],
            ),
            api_client.create_inbound_shipment_plan(
                inbound_plan_payload(
                    ctx["seller_id"], ctx["fc_id"], ctx["seller_version_before"],
                    "2026-08-20T00:00:00Z", "2026-08-21T00:00:00Z",
                ),
                ctx["fc_headers"],
            ),
            api_client.receive_plan(
                ctx["plan"]["id"],
                {
                    "received_lines": [
                        {
                            "shipment_line_item_id": ctx["line_item"]["id"],
                            "received_units": 60,
                            "unfulfillable_units": 0,
                        }
                    ]
                },
                ADMIN,
            ),
            api_client.create_sku_listing(
                sku_listing_payload(ctx["seller_id"], sku="SKU-ADJ"), ADJUDICATOR
            ),
        ]

    def test_each_role_is_refused_on_another_role_s_exclusive_write(self):
        """A seller cannot onboard itself, a centre cannot draft plans, an admin cannot receive
        and an adjudicator cannot create listings.

        PRD 2.1: "If the headers are well formed but the named role is not authorized for the
        requested operation, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD 4: "| POST | `/fulfillment/inbound-shipment-plans/{id}/receive` | Record a receipt at
        the destination centre; drives the completion fork and the discrepancy cascade |
        FcOperator |"

        Design: Corner/rbac/exclusive_write_families_reject_every_other_role_returns_4XX
        """
        ctx = self._in_transit_plan_of_sixty()
        for response in self._four_cross_role_writes(ctx):
            validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    def test_the_four_refusals_write_nothing_at_all(self):
        """No second seller, no second plan, no adjudicator listing and no receipt: the role
        gate sits above every other check, so nothing downstream ever ran.

        PRD 2.6: "2. Role authorization for the requested operation — `ERR_FORBIDDEN_ROLE`, on
        every endpoint."
        PRD 2.1: "This check precedes everything else, including request-body parsing."

        Design: Corner/rbac/exclusive_write_families_reject_every_other_role_returns_4XX
        """
        ctx = self._in_transit_plan_of_sixty()
        for _response in self._four_cross_role_writes(ctx):
            pass

        _listings, listing_meta = validate_paginated(
            api_client.list_seller_sku_listings(ctx["seller_id"], ctx["seller_headers"])
        )
        assert listing_meta["total_count"] == 1

        _plans, plan_meta = validate_paginated(
            api_client.list_inbound_shipment_plans(
                ctx["seller_headers"], params={"seller_account_id": ctx["seller_id"]}
            )
        )
        assert plan_meta["total_count"] == 1

        plan = read_plan(ctx["plan"]["id"], ctx["seller_id"])
        assert plan["status"] == "IN_TRANSIT"
        assert plan["received_units"] == 0
        assert seller_version(ctx["seller_id"]) == ctx["seller_version_before"]


class TestSharingIsPerEndpointNotPerEntity:
    """Every role may read a lot; only two may patch a centre; only two may read its fees."""

    def _one_lot_of_sixty_units(self) -> dict:
        return setup_received_lot(units=60)

    def test_all_four_roles_read_the_same_lot_body(self):
        """The seller, the holding centre, the adjudicator and the admin get byte-identical
        representations of the lot.

        PRD 4: "| GET | `/fulfillment/inventory-lots/{id}` | Read a lot with both state
        dimensions, every unit pool, its age bucket and accrued storage fees | MarketplaceAdmin,
        SellerOperator, FcOperator, ClaimsAdjudicator |"
        PRD 2.1: "The four roles are `SellerOperator`, `FcOperator`, `ClaimsAdjudicator` and
        `MarketplaceAdmin`."

        Design: Corner/rbac/shared_reads_open_to_all_roles_while_patch_is_shared_by_exactly_two
        """
        ctx = self._one_lot_of_sixty_units()
        bodies = [
            get_success_data(api_client.get_inventory_lot(ctx["lot_id"], headers))
            for headers in (ctx["seller_headers"], ctx["fc_headers"], ADJUDICATOR, ADMIN)
        ]
        for body in bodies:
            assert body["fulfillable_units"] == 60
            assert body["id"] == ctx["lot_id"]
        assert bodies[1] == bodies[0]
        assert bodies[2] == bodies[0]
        assert bodies[3] == bodies[0]

    def test_the_patch_pair_and_the_assessment_pair_are_different_pairs(self):
        """The centre and the admin may both revise posture while the seller may not; yet the
        centre is the one locked out of the lot's storage assessments.

        PRD 4: "| PATCH | `/fulfillment/fulfillment-centers/{id}` | Update receiving posture or
        window capacity | FcOperator, MarketplaceAdmin |"
        PRD 4: "| GET | `/fulfillment/inventory-lots/{id}/storage-fee-assessments` | List a
        lot's storage assessments, oldest first | MarketplaceAdmin, SellerOperator |"

        Design: Corner/rbac/shared_reads_open_to_all_roles_while_patch_is_shared_by_exactly_two
        """
        ctx = self._one_lot_of_sixty_units()
        assert set_receiving_posture(
            ctx["fc_id"], receiving_status="THROTTLED"
        )["receiving_status"] == "THROTTLED"

        by_admin = validate_success(
            api_client.update_fulfillment_center(
                ctx["fc_id"], {"receiving_status": "OPEN"}, ADMIN
            )
        )
        assert by_admin["receiving_status"] == "OPEN"

        validate_error(
            api_client.update_fulfillment_center(
                ctx["fc_id"], {"receiving_status": "SUSPENDED"}, ctx["seller_headers"]
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403,
        )
        validate_error(
            api_client.list_storage_fee_assessments(ctx["lot_id"], ctx["fc_headers"]),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403,
        )
        assert read_fulfillment_center(ctx["fc_id"])["receiving_status"] == "OPEN"


class TestPeersAreIsolatedByScope:
    """Two sellers and two centres, all holding the right role and still locked out."""

    def _seller_a_shipping_to_centre_a(self) -> dict:
        set_clock("2026-08-01T00:00:00Z")
        seller_a = register_seller()
        seller_b = register_seller(
            legal_name="Southgate Supply", storage_cubic_feet_entitlement=500.0000,
            unit_cost_cap_cents=150000,
        )
        centre_a = register_fulfillment_center()
        centre_b = register_fulfillment_center(fc_code="FC-B1", region_code="US-EAST")
        listing = create_listing(seller_a["id"])
        open_quota(seller_a["id"])
        built = create_in_transit_plan(
            seller_a["id"], centre_a["id"], listing["id"], 60,
            "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z",
        )
        return {
            "seller_a": seller_a["id"],
            "seller_b": seller_b["id"],
            "centre_a": centre_a["id"],
            "centre_b": centre_b["id"],
            "listing_id": listing["id"],
            "plan": built["plan"],
            "line_item": built["line_item"],
        }

    def test_a_peer_seller_and_a_peer_centre_get_scope_codes_not_the_role_code(self):
        """Both actors hold a role the endpoint accepts, so the refusals name the ownership
        gate rather than the role gate, and the plan is untouched.

        PRD 2.1: "A mismatch anywhere along that chain is rejected with
        `ERR_SELLER_SCOPE_VIOLATION` (HTTP 403)."
        PRD 2.1: "ownership checks compare the target resource's centre reference — a plan's
        `destination_fc_id`, or a lot's `fulfillment_center_id` — to `X-User-ID`, and a mismatch
        is rejected with `ERR_FC_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/peer_sellers_and_peer_fcs_are_isolated_by_scope_not_by_role
        """
        ctx = self._seller_a_shipping_to_centre_a()
        validate_error(
            api_client.cancel_plan(
                ctx["plan"]["id"], {}, make_seller_operator_headers(ctx["seller_b"])
            ),
            ApiErrorId.ERR_SELLER_SCOPE_VIOLATION.value, 403,
        )
        validate_error(
            api_client.receive_plan(
                ctx["plan"]["id"],
                {
                    "received_lines": [
                        {
                            "shipment_line_item_id": ctx["line_item"]["id"],
                            "received_units": 60,
                            "unfulfillable_units": 0,
                        }
                    ]
                },
                make_fc_operator_headers(ctx["centre_b"]),
            ),
            ApiErrorId.ERR_FC_SCOPE_VIOLATION.value, 403,
        )
        assert read_plan(ctx["plan"]["id"], ctx["seller_a"])["status"] == "IN_TRANSIT"

    def test_the_owning_centre_receives_the_same_plan_successfully(self):
        """Centre A completes the very receipt centre B was refused, and centre B's commitment
        ledger never moved.

        PRD 3.5: "Receipt is recorded by the `FcOperator` of the destination centre."
        PRD 2.7: "The third is the centre's receiving commitment: `committed_receiving_units` on
        a `FulfillmentCenter` always equals the sum of `declared_units` across plans whose
        `destination_fc_id` is that centre and whose `status` is `CONFIRMED`, `IN_TRANSIT` or
        `PARTIALLY_RECEIVED`."

        Design: Corner/rbac/peer_sellers_and_peer_fcs_are_isolated_by_scope_not_by_role
        """
        ctx = self._seller_a_shipping_to_centre_a()
        received = receive_plan(
            ctx["plan"]["id"], ctx["centre_a"],
            [(ctx["line_item"]["id"], 60, 0)],
        )
        assert received["status"] == "RECEIVED_COMPLETE"
        assert read_fulfillment_center(ctx["centre_b"])["committed_receiving_units"] == 0

        rows, meta = validate_paginated(
            api_client.list_inventory_lots(
                make_seller_operator_headers(ctx["seller_a"]),
                params={"fulfillment_center_id": ctx["centre_a"]},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["fulfillable_units"] == 60


class TestFilingAndAdjudicationAreSegregated:
    """Only the seller may file; only the adjudicator may question or decide."""

    def _sixty_fulfillable_and_twenty_damaged(self) -> dict:
        return setup_lot_with_split_pools(60, 20)

    def test_the_adjudicator_cannot_file_the_claim_the_seller_can(self):
        """The identical payload is refused to the adjudicator and accepted from the seller.

        PRD 2.1: "A `ClaimsAdjudicator` is the only role that may request further information on
        a claim or decide it, and it may never file or resubmit one."
        PRD 4: "| POST | `/fulfillment/reimbursement-claims` | File a reimbursement claim for
        lost or damaged units with evidence, inside the filing window | SellerOperator |"

        Design: Corner/rbac/claim_filing_and_adjudication_are_segregated_duties
        """
        ctx = self._sixty_fulfillable_and_twenty_damaged()
        payload = reimbursement_claim_payload(
            ctx["lot_id"], "DAMAGED_WAREHOUSE", 10, 3, "EV-10"
        )
        validate_error(
            api_client.file_reimbursement_claim(payload, ADJUDICATOR),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403,
        )
        filed = validate_success(
            api_client.file_reimbursement_claim(payload, ctx["seller_headers"]), 201
        )
        assert filed["status"] == "SUBMITTED"

    def test_neither_the_seller_nor_the_admin_may_move_the_claim(self):
        """The filer cannot approve its own claim and the most privileged onboarding role has no
        claim powers at all, so the claim is still SUBMITTED.

        PRD 2.1: "`MarketplaceAdmin` is likewise an opaque identifier not tied to any persisted
        entity, and it has no claim powers whatsoever and no inventory powers: it onboards seller
        accounts and fulfillment centers, opens quota periods, triggers storage billing runs and
        moves the logical clock, but it cannot file, resubmit, question or decide a claim, and it
        cannot touch a lot's unit pools."
        PRD 4: "| POST | `/fulfillment/reimbursement-claims/{id}/decide` | Approve or deny a
        submitted claim | ClaimsAdjudicator |"

        Design: Corner/rbac/claim_filing_and_adjudication_are_segregated_duties
        """
        ctx = self._sixty_fulfillable_and_twenty_damaged()
        claim = file_claim(
            ctx["lot_id"], ctx["seller_id"], "DAMAGED_WAREHOUSE", 10, 3,
            evidence_reference="EV-10",
        )
        validate_error(
            api_client.decide_claim(
                claim["id"],
                {"decision": "APPROVED", "decision_note": "self approval attempt"},
                ctx["seller_headers"],
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403,
        )
        validate_error(
            api_client.request_claim_info(
                claim["id"], {"information_request_note": "admin nudge"}, ADMIN
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403,
        )
        assert read_claim(claim["id"])["status"] == "SUBMITTED"

    def test_only_the_adjudicator_s_approval_moves_the_money_and_the_pool(self):
        """Ten damaged units at 1250 cents scaled by the 0.90 warehouse factor pay 11250 cents
        and leave the damaged pool at 10.

        PRD 3.8: "A type factor scales the result: 1.00 for `LOST_INBOUND`, 0.90 for
        `DAMAGED_WAREHOUSE` and 0.80 for `LOST_REMOVAL`."
        PRD 3.8: "The second link, caused by the first, decrements the claimed pool on the lot:
        `approved_units` is subtracted from the lot's `missing_units` for a `LOST_INBOUND` claim,
        from its `unfulfillable_units` for a `DAMAGED_WAREHOUSE` claim, or from its
        `units_removed` for a `LOST_REMOVAL` claim; when the lot's `missing_units` reaches 0 the
        reconciliation dimension moves `DISCREPANCY_CLAIMED → DISCREPANCY_RESOLVED`, and the
        seller's `open_discrepancy_units` drops by the same amount."

        Design: Corner/rbac/claim_filing_and_adjudication_are_segregated_duties
        """
        ctx = self._sixty_fulfillable_and_twenty_damaged()
        claim = file_claim(
            ctx["lot_id"], ctx["seller_id"], "DAMAGED_WAREHOUSE", 10, 3,
            evidence_reference="EV-10",
        )
        decided = decide_claim(claim["id"], "APPROVED", decision_note="photos accepted")
        assert decided["status"] == "APPROVED"
        assert decided["approved_units"] == 10
        assert decided["reimbursement_amount_cents"] == 11250

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["unfulfillable_units"] == 10
        assert lot["fulfillable_units"] == 60
        assert read_listing(ctx["listing_id"], ctx["seller_id"])["unfulfillable_units"] == 10
        assert read_seller(ctx["seller_id"])["reimbursement_credit_cents"] == 11250
