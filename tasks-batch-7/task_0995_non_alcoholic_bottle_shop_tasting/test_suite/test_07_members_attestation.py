"""Members and age attestation: the cyclic attestation lifecycle, revocation
cascade into orders and inventory, segregation of duties, validation priority,
and attestation RBAC (PRD §3.4, §2.1, §2.7, §4).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_line,
    create_attestation_payload,
    create_draft_order,
    get_lot,
    get_member,
    get_order,
    make_attested_member,
    make_category,
    make_lot,
    make_member,
    make_member_headers,
    make_shipping_rule,
    make_sku,
    make_special_order,
    set_clock,
    setup_packed_order,
    submit_order_fresh,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
STAFF = TEST_USERS["shop_staff_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
OFFICER_B = TEST_USERS["compliance_officer_b_headers"]


def _attest(member_id, attester_id, attested_on, doc_ref):
    return validate_success(
        api_client_create_attestation(member_id, attester_id, attested_on, doc_ref),
        201,
    )


def api_client_create_attestation(member_id, attester_id, attested_on, doc_ref):
    from test_helpers import api_client
    return api_client.create_attestation(
        member_id,
        create_attestation_payload(
            attested_by_user_id=attester_id,
            attested_on=attested_on,
            document_reference=doc_ref,
        ),
        STAFF,
    )


class TestAttestationCycle:
    def test_reject_then_reattest_then_approve(self, api):
        """PRD §3.4: "This submission is permitted when the member's
        `age_attestation_status` is either `UNVERIFIED` or `REJECTED` —
        re-attestation after a rejection is the only way back into the queue —
        and transitions the member to `PENDING_REVIEW` while creating a
        `ComplianceAttestation` row and bumping the member's `updated_at`."
        PRD §3.4: "Rejection, by contrast, requires only that the member is
        currently `PENDING_REVIEW`, and transitions the member to `REJECTED`.
        From `REJECTED` the cycle is open — a new attestation submission
        returns the member to `PENDING_REVIEW`."
        PRD §3.4: "Successful approval transitions the member to `ATTESTED`
        and recomputes the member's `loyalty_tier` (which in practice only
        changes if the lifetime-points thresholds happen to be crossed)."

        Design: Difficulty/non_linear_state_machine/member_attestation_cycle_with_revocation
        """
        from test_helpers import api_client
        set_clock()
        member = make_member(email="m6@x.com")
        att1 = _attest(member["id"], "staff_A", "2026-05-01", "doc1")
        assert get_member(member["id"])["age_attestation_status"] == "PENDING_REVIEW"
        validate_success(
            api_client.reject_attestation(member["id"], att1["id"], OFFICER), 200
        )
        assert get_member(member["id"])["age_attestation_status"] == "REJECTED"
        att2 = _attest(member["id"], "staff_B", "2026-05-02", "doc2")
        assert get_member(member["id"])["age_attestation_status"] == "PENDING_REVIEW"
        validate_success(
            api_client.approve_attestation(member["id"], att2["id"], OFFICER), 200
        )
        assert get_member(member["id"])["age_attestation_status"] == "ATTESTED"

    def test_attested_member_can_be_revoked_terminally(self, api):
        """PRD §3.4: "A `ComplianceOfficer` may also revoke a member whose
        `age_attestation_status` is currently `ATTESTED`. Revocation moves the
        member to `REVOKED` (a terminal state — there is no path back),
        immediately blocks all future orders containing `ADULT_ONLY_REQUIRED`
        SKUs for that member, and cascade-cancels any of that member's
        `Order` rows currently in `DRAFT` or `PICKING` that contain an
        `ADULT_ONLY_REQUIRED` SKU."

        Design: Difficulty/non_linear_state_machine/member_attestation_cycle_with_revocation
        """
        from test_helpers import api_client
        set_clock()
        member = make_attested_member(email="m6@x.com")
        validate_success(api_client.revoke_attestation(member["id"], OFFICER), 200)
        assert get_member(member["id"])["age_attestation_status"] == "REVOKED"


def _setup_adult_sku_picking_order(api):
    """ATTESTED member with a PICKING DTC order containing an
    ADULT_ONLY_REQUIRED SKU (abv 200 bps). Returns (member, order, lot)."""
    set_clock()
    category = make_category(code="tea8", display_name="Tea 8")
    sku = make_sku(category["id"], sku_code="sku-adult", base_price_cents=1500,
                   abv_basis_points=200)
    lot = make_lot(sku["id"], lot_code="L8", qty_received=10)
    member = make_attested_member(email="m8@x.com", attester_id="staff_X")
    make_shipping_rule(state_code="CA", tax_rate_bps=0)
    order = create_draft_order(member["id"], channel="DTC",
                               ship_to_state_code="CA")
    add_line(order["id"], member["id"], sku["id"], qty=2)
    order = validate_success(submit_order_fresh(order["id"], member["id"]), 200)
    return member, order, lot


class TestRevocationCascade:
    def test_revocation_cascade_cancels_picking_order(self, api):
        """PRD §3.4: "Revocation moves the member to `REVOKED` (a terminal
        state — there is no path back), immediately blocks all future orders
        containing `ADULT_ONLY_REQUIRED` SKUs for that member, and
        cascade-cancels any of that member's `Order` rows currently in
        `DRAFT` or `PICKING` that contain an `ADULT_ONLY_REQUIRED` SKU."
        PRD §3.1: "If none of those category branches apply and the SKU's
        `abv_basis_points` exceeds 50, the SKU's class is
        `ADULT_ONLY_REQUIRED`."

        Design: Difficulty/transitive_cascade/member_revocation_to_order_cancellation_chain
        """
        from test_helpers import api_client
        member, order, lot = _setup_adult_sku_picking_order(api)
        assert get_lot(lot["id"])["qty_remaining"] == 8
        validate_success(api_client.revoke_attestation(member["id"], OFFICER), 200)
        assert get_member(member["id"])["age_attestation_status"] == "REVOKED"
        order_after = get_order(order["id"])
        assert order_after["fulfillment_status"] == "CANCELLED", (
            "revocation must cascade-cancel the PICKING order"
        )
        assert order_after["payment_status"] == "VOIDED"

    def test_revocation_cascade_restores_inventory(self, api):
        """PRD §3.4: "cascade-cancels any of that member's `Order` rows
        currently in `DRAFT` or `PICKING` that contain an `ADULT_ONLY_REQUIRED`
        SKU."
        PRD §3.8: "the cancellation restores `InventoryLot.qty_remaining` for
        every entry in every line's `lot_allocation`, recomputes
        `on_hand_cached` for the affected SKUs, sets `payment_status` to
        `VOIDED`, reverses the loyalty redemption, and transitions the order
        to `CANCELLED`."

        Design: Difficulty/transitive_cascade/member_revocation_to_order_cancellation_chain
        """
        from test_helpers import api_client
        member, order, lot = _setup_adult_sku_picking_order(api)
        assert get_lot(lot["id"])["qty_remaining"] == 8
        validate_success(api_client.revoke_attestation(member["id"], OFFICER), 200)
        assert get_lot(lot["id"])["qty_remaining"] == 10, (
            "cascade-cancel must restore the allocated bottles"
        )
        assert get_lot(lot["id"])["status"] == "ACTIVE"


def _setup_packed_then_revoked(api):
    """Order containing an ADULT_ONLY_REQUIRED SKU walked to PACKED by an
    ATTESTED member; the member's attestation is then revoked (the cascade
    only touches DRAFT/PICKING orders, so the PACKED order survives) and the
    member's resubmission hits both a state violation (not DRAFT) and an
    age-attestation violation (REVOKED, not ATTESTED)."""
    from test_helpers import api_client
    set_clock()
    category = make_category(code="tea9", display_name="Tea 9")
    sku = make_sku(category["id"], sku_code="sku-a9", base_price_cents=2000,
                   abv_basis_points=200)
    make_lot(sku["id"], lot_code="L9", qty_received=10)
    member = make_attested_member(email="m9a@x.com", attester_id="staff1")
    make_shipping_rule(state_code="CA", tax_rate_bps=0)
    order = create_draft_order(member["id"], channel="DTC",
                               ship_to_state_code="CA")
    add_line(order["id"], member["id"], sku["id"], qty=1)
    order = validate_success(submit_order_fresh(order["id"], member["id"]), 200)
    validate_success(api_client.pack_order(order["id"], STAFF), 200)
    validate_success(api_client.revoke_attestation(member["id"], OFFICER), 200)
    return member, order


class TestValidationPriorityStateFirst:
    def test_state_violation_precedes_age_attestation(self, api):
        """PRD §2.7: "5. State — the target entity's current state permits
        the requested transition (`ERR_INVALID_STATE`)."
        PRD §2.7: "6. Age attestation — the member is `ATTESTED` when an
        `ADULT_ONLY_REQUIRED` SKU is involved (`ERR_AGE_ATTESTATION_REQUIRED`)."
        PRD §2.7: "Because checks are evaluated in this order, a single
        malformed call surfaces exactly one error — the earliest in this list
        that applies."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_priority
        """
        member, order = _setup_packed_then_revoked(api)
        assert get_member(member["id"])["age_attestation_status"] == "REVOKED"
        resp = submit_order_fresh(order["id"], member["id"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_priority_rejection_leaves_packed_order_unchanged(self, api):
        """PRD §2.7: "When a single request could fail more than one check,
        the server evaluates checks in a fixed priority order and returns the
        first failure. The ordering matters because a higher-priority failure
        masks lower-priority ones."
        PRD §3.8: "From `PICKING` a `ShopStaff` operator packs the order,
        transitioning `fulfillment_status` to `PACKED` and bumping `version`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_priority
        """
        member, order = _setup_packed_then_revoked(api)
        resp = submit_order_fresh(order["id"], member["id"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_order(order["id"])
        assert after["fulfillment_status"] == "PACKED"
        assert after["payment_status"] == "AUTHORIZED"


class TestSegregationOfDuties:
    def test_special_order_self_approval_rejected(self, api):
        """PRD §3.10: "Approval enforces segregation of duties — the
        `approved_by_user_id` must differ from the requesting `member_id`,
        with violation rejected as `ERR_SEGREGATION_OF_DUTIES` — and requires
        that the resolved SKU's `discontinued` flag be false."

        Design: Corner/validations/segregation_of_duties_special_order_approve
        """
        from test_helpers import api_client
        set_clock()
        member = make_member(email="mso@x.com")
        category = make_category(code="cso", display_name="CSO")
        sku = make_sku(category["id"], sku_code="sso", base_price_cents=500)
        special = make_special_order(member["id"], requested_sku_code="sso",
                                     quantity=1, deposit_cents=0)
        resp = api_client.approve_special_order(
            special["id"],
            {"resolved_sku_id": sku["id"], "approved_by_user_id": member["id"]},
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestAttestationRbac:
    def test_shop_staff_cannot_approve_attestation(self, api):
        """PRD §4: "| POST | `/nabs/members/{id}/attestations/{att_id}/approve`
        | Approve attestation | ComplianceOfficer |"
        PRD §2.1: "A request whose role is not on the authorized list for the
        target endpoint is rejected with `ERR_UNAUTHORIZED`."
        PRD §2.1: "a `ComplianceOfficer` approving a `ComplianceAttestation`
        may not be the `ShopStaff` operator who originally submitted it."

        Design: Corner/roles/shop_staff_cannot_approve_attestation
        """
        from test_helpers import api_client
        set_clock()
        member = make_member(email="msod@x.com")
        attestation = _attest(member["id"], "staff_Z", "2026-05-01", "d")
        resp = api_client.approve_attestation(member["id"], attestation["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_compliance_officer_cannot_pack_order(self, api):
        """PRD §4: "| POST | `/nabs/orders/{id}/pack` | Mark an order packed |
        ShopStaff |"
        PRD §2.1: "A request whose role is not on the authorized list for the
        target endpoint is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/roles/compliance_officer_cannot_pack_order
        """
        from test_helpers import api_client
        order, member, sku = setup_packed_order(channel="RETAIL")
        # Order is actually PACKED now; even a well-formed pack attempt by a
        # ComplianceOfficer must be refused on role grounds. Use a fresh
        # PICKING order to keep the state precondition satisfiable.
        set_clock()
        make_shipping_rule(state_code="CA", tax_rate_bps=0)
        order2, member2, sku2 = _fresh_picking_order()
        resp = api_client.pack_order(order2["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def _fresh_picking_order():
    from test_helpers import setup_submitted_order
    return setup_submitted_order(channel="RETAIL")
