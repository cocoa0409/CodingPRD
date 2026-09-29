"""The validation ladder, rung by rung, on requests that violate exactly one rule.

"Every request is validated as an ordered ladder, and the first violation encountered
wins: the request is rejected with that rule's error and no later rule is evaluated."
Each test below stages a single violation so that the rung under test is the only one
that can fire, and then proves that the refused write moved nothing.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_BULK_QUANTITY_LIMIT_EXCEEDED,
    ERR_CLAIM_WINDOW_EXPIRED,
    ERR_DUPLICATE_LISTING,
    ERR_EVIDENCE_INCOMPLETE,
    ERR_EVIDENCE_ROUND_LIMIT_EXCEEDED,
    ERR_IDENTITY_VERIFICATION_REQUIRED,
    ERR_INSUFFICIENT_BALANCE,
    ERR_INVALID_REQUEST,
    ERR_PACKAGING_SEAL_BROKEN,
    ERR_REISSUE_LIMIT_EXCEEDED,
    ERR_STORE_NOT_FOUND,
)
from test_helpers.constants import ABSENT_UUID, CLOCK_ORIGIN
from test_helpers.factories import (
    bulk_decision_payload,
    bulk_order_payload,
    card_rack_payload,
    claim_decision_payload,
    evidence_request_payload,
    omit,
    physical_issuance_payload,
    redemption_payload,
    reseller_listing_payload,
    victim_claim_payload,
)
from test_helpers.fixtures import (
    advance_clock,
    capture_identity,
    create_rack,
    create_store,
    file_claim,
    funded_digital_card,
    funded_physical_card,
    hold_on_card,
    open_bulk_order,
    open_period,
    parse_instant,
    read_card,
    read_claim,
    read_period,
    read_rack,
    read_store,
    redeem,
    request_evidence,
    resubmit_evidence,
    stock_card,
    submit_listing,
    total_count,
    validate_listing,
)
from test_helpers.test_users import (
    make_fraud_analyst_headers,
    make_platform_admin_headers,
    make_pos_associate_headers,
    make_reseller_partner_headers,
    make_risk_manager_headers,
)


class TestPackagingSealAttestation:
    """The tamper-evident packaging attestation is checked on the request itself."""

    def _store_with_two_stocked_cards(self, client):
        """An OPEN-floor store, an INTACT rack and two INACTIVE cards on it."""
        store = create_store(
            client, name="Seal Check Store", region_code="NE", address_line="30 Seal Sq"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-SC", expected_card_count=6
        )
        card_a = stock_card(
            client, store["id"], rack["id"], card_number_masked="****-****-****-6001"
        )
        card_b = stock_card(
            client, store["id"], rack["id"], card_number_masked="****-****-****-6002"
        )
        return {"store": store, "rack": rack, "card_a": card_a, "card_b": card_b}

    def test_broken_seal_on_a_physical_request_is_refused(self, client):
        """"Three refusals guard the opening of a request, and the packaging attestation is
        the first of them: a `PHYSICAL` request that declares `packaging_seal_intact` false
        is refused with `ERR_PACKAGING_SEAL_BROKEN`, because packaging that has already been
        opened means the card data may already be in a criminal's hands."

        Design: Corner/validations/physical_issuance_with_broken_seal_is_rejected
        """
        world = self._store_with_two_stocked_cards(client)

        response = client.create_issuance_request(
            physical_issuance_payload(
                world["store"]["id"],
                world["rack"]["id"],
                world["card_a"]["id"],
                5000,
                pos_terminal_id="T-60",
                packaging_seal_intact=False,
            ),
            make_pos_associate_headers(),
        )

        assert response.status_code == 422, response.text
        validate_error(response, ERR_PACKAGING_SEAL_BROKEN, 422)

    def test_the_refused_request_funds_nothing_and_does_not_touch_the_rack(self, client):
        """"A request that survives all three is created in state `SUBMITTED`, with
        `screening_score`, `screening_components` and `decline_reason` all empty and
        `screened_at` not yet stamped."
        "The card is created with `channel` `PHYSICAL`, a funding state of `INACTIVE`, a
        fraud posture of `CLEAR`, `face_value_cents` of 0 and every balance figure at 0."
        "Classification is fully re-derived on every audit and is deliberately not sticky,
        with one exception."

        Design: Corner/validations/physical_issuance_with_broken_seal_is_rejected
        """
        world = self._store_with_two_stocked_cards(client)

        client.create_issuance_request(
            physical_issuance_payload(
                world["store"]["id"],
                world["rack"]["id"],
                world["card_a"]["id"],
                5000,
                pos_terminal_id="T-60",
                packaging_seal_intact=False,
            ),
            make_pos_associate_headers(),
        )

        listed = client.list_issuance_requests(
            make_platform_admin_headers(), {"card_id": world["card_a"]["id"]}
        )
        assert total_count(listed) == 0, "the refused request must not be persisted"

        card = read_card(client, world["card_a"]["id"])
        assert card["activation_state"] == "INACTIVE"
        assert card["current_balance_cents"] == 0

        rack = read_rack(client, world["rack"]["id"])
        assert rack["tamper_state"] == "INTACT"

    def test_the_same_request_with_the_seal_intact_is_accepted(self, client):
        """"A request that survives all three is created in state `SUBMITTED`, with
        `screening_score`, `screening_components` and `decline_reason` all empty and
        `screened_at` not yet stamped."

        Design: Corner/validations/physical_issuance_with_broken_seal_is_rejected
        """
        world = self._store_with_two_stocked_cards(client)

        response = client.create_issuance_request(
            physical_issuance_payload(
                world["store"]["id"],
                world["rack"]["id"],
                world["card_b"]["id"],
                5000,
                pos_terminal_id="T-60",
                packaging_seal_intact=True,
            ),
            make_pos_associate_headers(),
        )

        assert response.status_code == 201, response.text
        request = validate_success(response, 201)
        assert request["state"] == "SUBMITTED"
        assert request["packaging_seal_intact"] is True


class TestBulkIdentityGate:
    """Identity capture is conditional on the computed order total, not on the quantity."""

    def _order_above_the_identity_threshold(self, client):
        """A store plus a 20-card order at 5000 cents each, whose total lands above the
        threshold at which "government identity capture becomes mandatory"."""
        store = create_store(
            client, name="Identity Gate Store", region_code="MW", address_line="31 Gate Rd"
        )
        order = open_bulk_order(
            client,
            store["id"],
            card_quantity=20,
            face_value_cents_each=5000,
            purchaser_name="Halberd Logistics Inc",
            payment_method="CORPORATE_ACH",
        )
        return {"store": store, "order": order}

    def test_the_order_is_priced_and_lands_in_pending_identity(self, client):
        """"First, `face_value_subtotal_cents` is the card quantity multiplied by the
        per-card face value — exact, with no rounding required."
        "from 100000 up to but not including 500000 cents it is 225 basis points"
        "Third, `activation_fee_cents` is the subtotal multiplied by that basis-point figure
        and divided by 10000, rounded half up **exactly once** over the whole order.
        Fourth, `total_cents` is the subtotal plus the activation fee."
        "When `total_cents` is at or above `bulk_identity_threshold_cents` the order is
        created in `PENDING_IDENTITY`, because government identity is mandatory before
        approval."

        Design: Corner/validations/bulk_approval_without_identity_above_threshold_is_rejected
        """
        order = self._order_above_the_identity_threshold(client)["order"]

        assert order["face_value_subtotal_cents"] == 100000
        assert order["fee_rate_bps"] == 225
        assert order["activation_fee_cents"] == 2250
        assert order["total_cents"] == 102250
        assert order["state"] == "PENDING_IDENTITY"

    def test_approval_without_a_captured_identity_is_refused(self, client):
        """"Approval is admitted from either `PENDING_IDENTITY` or `IDENTITY_VERIFIED` and is
        guarded twice. The store's floor must not be `SUSPENDED`, otherwise the approval is
        refused with `ERR_STORE_FLOOR_SUSPENDED`; and, on an order whose total is at or above
        `bulk_identity_threshold_cents`, `identity_id_number_hash` must not be empty,
        otherwise the approval is refused with `ERR_IDENTITY_VERIFICATION_REQUIRED`."

        Design: Corner/validations/bulk_approval_without_identity_above_threshold_is_rejected
        """
        world = self._order_above_the_identity_threshold(client)

        response = client.decide_bulk_purchase_order(
            world["order"]["id"],
            bulk_decision_payload("APPROVE", decision_note="approving before the ID is taken"),
            make_risk_manager_headers("risk-61"),
        )

        assert response.status_code == 422, response.text
        validate_error(response, ERR_IDENTITY_VERIFICATION_REQUIRED, 422)

        order = validate_success(
            client.get_bulk_purchase_order(world["order"]["id"], make_platform_admin_headers())
        )
        assert order["state"] == "PENDING_IDENTITY"
        assert not order["decided_by_user_id"], "a refused approval records no decider"

    def test_the_identical_approval_succeeds_once_the_identity_is_on_file(self, client):
        """"Those land on the order as `identity_id_type` — one of `DRIVERS_LICENSE`,
        `PASSPORT`, `STATE_ID` or `MILITARY_ID` — together with `identity_id_number_hash`, a
        salted hash of the document number, and `identity_id_expiry_date`, the document's
        expiry. The order moves to `IDENTITY_VERIFIED` and its `version` increments."
        "Either terminal decision records `decided_by_user_id` from the caller's `X-User-ID`
        along with the `decision_note`, and increments the order's `version`."

        Design: Corner/validations/bulk_approval_without_identity_above_threshold_is_rejected
        """
        world = self._order_above_the_identity_threshold(client)

        verified = capture_identity(
            client,
            world["order"]["id"],
            id_type="DRIVERS_LICENSE",
            id_number_hash="idh-61",
            id_expiry_date="2030-04-30",
        )
        assert verified["state"] == "IDENTITY_VERIFIED"
        assert verified["identity_id_type"] == "DRIVERS_LICENSE"
        assert verified["identity_id_number_hash"] == "idh-61"
        assert verified["identity_id_expiry_date"] == "2030-04-30"

        response = client.decide_bulk_purchase_order(
            world["order"]["id"],
            bulk_decision_payload("APPROVE", decision_note="ID on file, approved"),
            make_risk_manager_headers("risk-61"),
        )

        assert response.status_code == 200, response.text
        decided = validate_success(response, 200)
        assert decided["state"] == "APPROVED"
        assert decided["decided_by_user_id"] == "risk-61"


class TestChannelAppropriateEvidence:
    """The evidence bar an approval must clear depends on the claimed card's channel."""

    def _two_claims_on_one_receipt_each(self, client):
        """A PHYSICAL card and a DIGITAL card, each funded at 5000 cents and each drained by
        one 2000-cent redemption, each carrying a claim filed with a receipt and no
        packaging photo, plus an OPEN period covering the current instant."""
        store = create_store(
            client, name="Evidence Channel Store", region_code="SE", address_line="32 Evidence Ave"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-EC", expected_card_count=6
        )
        period = open_period(client, label="2026-08 evidence")

        physical = funded_physical_card(client, 5000, store=store, rack=rack)
        redeem(client, physical["card"]["id"], 2000, store["id"], pos_terminal_id="T-62")

        digital = funded_digital_card(client, 5000)
        redeem(client, digital["card"]["id"], 2000, store["id"], pos_terminal_id="T-62")

        claim_physical = file_claim(
            client,
            physical["card"]["id"],
            disputed_amount_cents=2000,
            purchased_at=CLOCK_ORIGIN,
            headers=make_fraud_analyst_headers("analyst-62"),
            claimant_name="Marta Ilves",
            claimant_contact="marta@example.test",
            purchase_receipt_ref="RCPT-6201",
        )
        claim_digital = file_claim(
            client,
            digital["card"]["id"],
            disputed_amount_cents=2000,
            purchased_at=CLOCK_ORIGIN,
            headers=make_fraud_analyst_headers("analyst-62"),
            claimant_name="Owen Brady",
            claimant_contact="owen@example.test",
            purchase_receipt_ref="RCPT-6202",
        )
        return {
            "store": store,
            "period": period,
            "physical_card_id": physical["card"]["id"],
            "digital_request": digital["request"],
            "digital_card_id": digital["card"]["id"],
            "claim_physical": claim_physical,
            "claim_digital": claim_digital,
        }

    def test_a_physical_claim_without_a_packaging_photo_cannot_be_approved(self, client):
        """"A receipt reference is mandatory for every claim; a packaging photo reference is
        additionally mandatory when the referenced card's `channel` is `PHYSICAL`, because a
        digital card has no packaging to photograph. A missing required reference is refused
        with `ERR_EVIDENCE_INCOMPLETE`. A `DIGITAL` card therefore approves on a receipt
        alone, while a `PHYSICAL` card with a receipt but no packaging photo does not."

        Design: Corner/validations/physical_claim_without_packaging_photo_cannot_be_approved
        """
        world = self._two_claims_on_one_receipt_each(client)

        response = client.decide_victim_claim(
            world["claim_physical"]["id"],
            claim_decision_payload("APPROVE", decision_note="physical claim, receipt only"),
            make_risk_manager_headers("risk-62"),
        )

        assert response.status_code == 422, response.text
        validate_error(response, ERR_EVIDENCE_INCOMPLETE, 422)

        claim = read_claim(client, world["claim_physical"]["id"])
        assert claim["state"] == "SUBMITTED"
        assert not claim["reissue_amount_cents"], "no payout is computed on a refused approval"
        assert not claim["reissued_card_id"], "no replacement card is minted"

        card = read_card(client, world["physical_card_id"])
        assert card["activation_state"] == "ACTIVE"
        assert card["current_balance_cents"] == 3000

    def test_a_digital_claim_approves_on_the_same_single_receipt(self, client):
        """"A receipt reference is mandatory for every claim; a packaging photo reference is
        additionally mandatory when the referenced card's `channel` is `PHYSICAL`, because a
        digital card has no packaging to photograph."
        "`recovery_factor_bps` is applied to **each line individually**, and each line's
        result is rounded to whole cents half-up **before** the addition; `gross_reissue_cents`
        is the sum of those already-rounded per-line figures."
        "Fourth, the claimant ceiling applies: `reissue_amount_cents` is the smaller of
        `gross_reissue_cents` and `disputed_amount_cents`."
        "Fifth, `residual_transfer_cents` takes whatever is still live on the compromised card
        — its `current_balance_cents` at that moment — so that value is moved rather than
        duplicated."

        Design: Corner/validations/physical_claim_without_packaging_photo_cannot_be_approved
        """
        world = self._two_claims_on_one_receipt_each(client)

        assert world["digital_request"]["state"] == "APPROVED"
        assert read_card(client, world["digital_card_id"])["channel"] == "DIGITAL"

        response = client.decide_victim_claim(
            world["claim_digital"]["id"],
            claim_decision_payload("APPROVE", decision_note="digital claim, receipt only"),
            make_risk_manager_headers("risk-62"),
        )

        assert response.status_code == 200, response.text
        claim = validate_success(response, 200)
        assert claim["state"] == "APPROVED"
        assert claim["unauthorized_line_count"] == 1
        assert claim["gross_reissue_cents"] == 1700
        assert claim["reissue_amount_cents"] == 1700
        assert claim["residual_transfer_cents"] == 3000

    def test_the_digital_approval_moves_the_residual_onto_a_replacement_card(self, client):
        """"Hop two follows from the claim being approved: a replacement gift card is minted,
        inheriting the original card's `channel` and `store_id`, taking no `rack_id` at all,
        carrying `reissued_from_card_id` pointed at the original, and created directly in
        `ACTIVE` — it is never stocked and never activated through the ordinary route. A
        ledger event of `type` `REISSUE_CREDIT` is appended on it for `reissue_amount_cents`
        plus `residual_transfer_cents`, and the claim's `reissued_card_id` is set."
        "Hop three follows from the replacement now holding the transferred residual: the
        original card transitions to `CLOSED` — from `ACTIVE` or from `DEPLETED` alike"
        "Hop four follows from the original card having been written off: the `OPEN` liability
        period whose span contains the logical now has its `unauthorized_writeoff_cents`
        incremented by `reissue_amount_cents`"

        Design: Corner/validations/physical_claim_without_packaging_photo_cannot_be_approved
        """
        world = self._two_claims_on_one_receipt_each(client)

        claim = validate_success(
            client.decide_victim_claim(
                world["claim_digital"]["id"],
                claim_decision_payload("APPROVE", decision_note="digital claim, receipt only"),
                make_risk_manager_headers("risk-62"),
            ),
            200,
        )

        original = read_card(client, world["digital_card_id"])
        assert original["activation_state"] == "CLOSED"
        assert original["current_balance_cents"] == 0

        replacement = read_card(client, claim["reissued_card_id"])
        assert replacement["activation_state"] == "ACTIVE"
        assert replacement["current_balance_cents"] == 4700
        assert replacement["reissued_from_card_id"] == world["digital_card_id"]

        period = read_period(client, world["period"]["id"])
        assert period["unauthorized_writeoff_cents"] == 1700
        assert period["state"] == "OPEN"


class TestClaimFilingWindow:
    """The filing window's far edge is inclusive, and the day after it is not."""

    def _card_at_the_window_edge(self, client):
        """A 9000-cent ACTIVE card bought at the clock origin, with the clock then moved to
        exactly ninety days later — the last instant at which a claim may still be filed."""
        store = create_store(
            client, name="Claim Window Store", region_code="NW", address_line="33 Window Way"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-CW", expected_card_count=6
        )
        built = funded_physical_card(client, 9000, store=store, rack=rack)
        clock = advance_clock(client, "2026-10-30T00:00:00Z")
        return {"store": store, "card_id": built["card"]["id"], "clock": clock}

    def test_a_claim_filed_exactly_at_the_window_edge_is_accepted(self, client):
        """"`purchased_at` starts the filing window: intake is refused with
        `ERR_CLAIM_WINDOW_EXPIRED` when the elapsed time from `purchased_at` to the logical now
        exceeds `claim_window_days`. The boundary is inclusive, so a claim filed exactly
        `claim_window_days` after purchase is accepted and one filed a moment later is not."
        "A successful intake creates the claim in state `SUBMITTED` with `evidence_round` at 0,
        `missing_evidence_kinds` empty, `intake_user_id` recorded from the caller's
        `X-User-ID`"

        Design: Corner/validations/claim_filed_one_day_past_the_window_is_rejected
        """
        world = self._card_at_the_window_edge(client)

        assert parse_instant(world["clock"]["current_utc"]) == parse_instant(
            "2026-10-30T00:00:00Z"
        )
        assert world["clock"]["expired_hold_count"] == 0, "no holds exist to sweep"

        response = client.create_victim_claim(
            victim_claim_payload(
                world["card_id"],
                disputed_amount_cents=4000,
                purchased_at=CLOCK_ORIGIN,
                claimant_name="Priya Raman",
                claimant_contact="priya@example.test",
                purchase_receipt_ref="RCPT-6301",
                packaging_photo_ref="PHOTO-6301",
            ),
            make_fraud_analyst_headers("analyst-63"),
        )

        assert response.status_code == 201, response.text
        claim = validate_success(response, 201)
        assert claim["state"] == "SUBMITTED"
        assert parse_instant(claim["created_at"]) == parse_instant("2026-10-30T00:00:00Z")
        assert parse_instant(claim["purchased_at"]) == parse_instant(CLOCK_ORIGIN)

    def test_a_claim_filed_one_day_later_is_refused_and_nothing_persists(self, client):
        """"`purchased_at` starts the filing window: intake is refused with
        `ERR_CLAIM_WINDOW_EXPIRED` when the elapsed time from `purchased_at` to the logical now
        exceeds `claim_window_days`. The boundary is inclusive, so a claim filed exactly
        `claim_window_days` after purchase is accepted and one filed a moment later is not."

        Design: Corner/validations/claim_filed_one_day_past_the_window_is_rejected
        """
        world = self._card_at_the_window_edge(client)

        file_claim(
            client,
            world["card_id"],
            disputed_amount_cents=4000,
            purchased_at=CLOCK_ORIGIN,
            headers=make_fraud_analyst_headers("analyst-63"),
            claimant_name="Priya Raman",
            claimant_contact="priya@example.test",
            purchase_receipt_ref="RCPT-6301",
            packaging_photo_ref="PHOTO-6301",
        )

        later = advance_clock(client, "2026-10-31T00:00:00Z")
        assert parse_instant(later["current_utc"]) == parse_instant("2026-10-31T00:00:00Z")

        response = client.create_victim_claim(
            victim_claim_payload(
                world["card_id"],
                disputed_amount_cents=1000,
                purchased_at=CLOCK_ORIGIN,
                claimant_name="Priya Raman",
                claimant_contact="priya@example.test",
                purchase_receipt_ref="RCPT-6302",
                packaging_photo_ref="PHOTO-6302",
            ),
            make_fraud_analyst_headers("analyst-63"),
        )

        assert response.status_code == 422, response.text
        validate_error(response, ERR_CLAIM_WINDOW_EXPIRED, 422)

        listed = client.list_victim_claims(
            make_platform_admin_headers(), {"card_id": world["card_id"]}
        )
        assert total_count(listed) == 1, "only the in-window claim persisted"

        card = read_card(client, world["card_id"])
        assert card["activation_state"] == "ACTIVE"
        assert card["current_balance_cents"] == 9000


class TestBulkQuantityLimit:
    """The size check runs before any pricing, and it bites one card over the limit."""

    def test_one_card_over_the_quantity_limit_is_refused(self, client):
        """"Before anything is priced, the order is size-checked: a `card_quantity` greater than
        `bulk_quantity_limit` is refused with `ERR_BULK_QUANTITY_LIMIT_EXCEEDED`. A quantity
        exactly equal to the limit is accepted; one more than the limit is not."

        Design: Corner/validations/bulk_order_one_card_over_the_quantity_limit_is_rejected
        """
        store = create_store(
            client, name="Quantity Limit Store", region_code="SW", address_line="34 Limit Ln"
        )

        response = client.create_bulk_purchase_order(
            bulk_order_payload(
                store["id"],
                card_quantity=26,
                face_value_cents_each=2000,
                purchaser_name="Overreach Events LLC",
                payment_method="CREDIT",
            ),
            make_pos_associate_headers(),
        )

        assert response.status_code == 422, response.text
        validate_error(response, ERR_BULK_QUANTITY_LIMIT_EXCEEDED, 422)

        listed = client.list_bulk_purchase_orders(
            make_platform_admin_headers(), {"store_id": store["id"]}
        )
        assert total_count(listed) == 0, "the refused order was not persisted"

    def test_exactly_at_the_quantity_limit_is_accepted_and_priced(self, client):
        """"Before anything is priced, the order is size-checked: a `card_quantity` greater than
        `bulk_quantity_limit` is refused with `ERR_BULK_QUANTITY_LIMIT_EXCEEDED`. A quantity
        exactly equal to the limit is accepted; one more than the limit is not."
        "from 25000 up to but not including 100000 cents the rate is 150 basis points"
        "When `total_cents` is at or above `bulk_identity_threshold_cents` the order is created
        in `PENDING_IDENTITY`, because government identity is mandatory before approval."

        Design: Corner/validations/bulk_order_one_card_over_the_quantity_limit_is_rejected
        """
        store = create_store(
            client, name="Quantity Limit Store", region_code="SW", address_line="34 Limit Ln"
        )

        response = client.create_bulk_purchase_order(
            bulk_order_payload(
                store["id"],
                card_quantity=25,
                face_value_cents_each=2000,
                purchaser_name="Overreach Events LLC",
                payment_method="CREDIT",
            ),
            make_pos_associate_headers(),
        )

        assert response.status_code == 201, response.text
        order = validate_success(response, 201)
        assert order["card_quantity"] == 25
        assert order["face_value_subtotal_cents"] == 50000
        assert order["fee_rate_bps"] == 150
        assert order["activation_fee_cents"] == 750
        assert order["total_cents"] == 50750
        assert order["state"] == "PENDING_IDENTITY"


class TestEvidenceRoundLimit:
    """Each evidence request is legal on its own; their collective count is capped."""

    def _claim_with_three_completed_rounds(self, client):
        """A SUBMITTED claim that has been bounced back and resubmitted three times, so its
        `evidence_round` has climbed to the policy limit."""
        store = create_store(
            client, name="Evidence Rounds Store", region_code="NE", address_line="35 Round Rd"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-ER", expected_card_count=6
        )
        built = funded_physical_card(client, 9000, store=store, rack=rack)
        claim = file_claim(
            client,
            built["card"]["id"],
            disputed_amount_cents=3000,
            purchased_at=CLOCK_ORIGIN,
            headers=make_fraud_analyst_headers("analyst-64"),
            claimant_name="Ines Duarte",
            claimant_contact="ines@example.test",
        )
        analyst = make_fraud_analyst_headers("analyst-64")
        rounds = []
        rounds.append(
            request_evidence(
                client, claim["id"], ["PURCHASE_RECEIPT", "PACKAGING_PHOTO"], headers=analyst
            )
        )
        rounds.append(
            resubmit_evidence(
                client, claim["id"], headers=analyst, purchase_receipt_ref="RCPT-6401-a"
            )
        )
        rounds.append(
            request_evidence(client, claim["id"], ["PACKAGING_PHOTO"], headers=analyst)
        )
        rounds.append(
            resubmit_evidence(
                client,
                claim["id"],
                headers=analyst,
                purchase_receipt_ref=omit,
                packaging_photo_ref="PHOTO-6401-b",
            )
        )
        rounds.append(
            request_evidence(client, claim["id"], ["PACKAGING_PHOTO"], headers=analyst)
        )
        rounds.append(
            resubmit_evidence(
                client,
                claim["id"],
                headers=analyst,
                purchase_receipt_ref=omit,
                packaging_photo_ref="PHOTO-6401-c",
            )
        )
        return {"claim_id": claim["id"], "rounds": rounds, "analyst": analyst}

    def test_each_completed_cycle_climbs_the_round_counter_by_one(self, client):
        """"On the outbound leg a `FraudAnalyst` bounces the claim back for what is missing,
        supplying `missing_evidence_kinds`; the claim moves `SUBMITTED → EVIDENCE_REQUESTED`,
        `evidence_round` increments by 1, the requested kinds are recorded, and `version`
        increments."
        "Critically, resubmission does **not** reset `evidence_round`."

        Design: Corner/validations/fourth_evidence_request_exceeds_the_round_limit
        """
        rounds = self._claim_with_three_completed_rounds(client)["rounds"]

        assert rounds[0]["state"] == "EVIDENCE_REQUESTED"
        assert rounds[0]["evidence_round"] == 1
        assert rounds[1]["state"] == "SUBMITTED"
        assert rounds[2]["evidence_round"] == 2
        assert rounds[3]["state"] == "SUBMITTED"
        assert rounds[4]["evidence_round"] == 3
        assert rounds[5]["state"] == "SUBMITTED"
        assert rounds[5]["evidence_round"] == 3

    def test_the_fourth_request_is_refused_and_the_claim_stays_decidable(self, client):
        """"That counter only ever climbs, and it is what bounds the loop: a further evidence
        request is refused with `ERR_EVIDENCE_ROUND_LIMIT_EXCEEDED` once `evidence_round` has
        already reached `claim_evidence_round_limit`."
        "A claim can therefore ping-pong between the two states at most
        `claim_evidence_round_limit` times, and one that has exhausted its rounds is stuck in
        `SUBMITTED` and must be decided on the evidence in hand."
        "the claim moves `EVIDENCE_REQUESTED → SUBMITTED`, and **only the references actually
        supplied are overwritten** — an omitted reference retains whatever it already held
        rather than being cleared."

        Design: Corner/validations/fourth_evidence_request_exceeds_the_round_limit
        """
        world = self._claim_with_three_completed_rounds(client)

        response = client.request_claim_evidence(
            world["claim_id"],
            evidence_request_payload(["PACKAGING_PHOTO"]),
            world["analyst"],
        )

        assert response.status_code == 422, response.text
        validate_error(response, ERR_EVIDENCE_ROUND_LIMIT_EXCEEDED, 422)

        claim = read_claim(client, world["claim_id"])
        assert claim["state"] == "SUBMITTED"
        assert claim["evidence_round"] == 3
        assert claim["purchase_receipt_ref"] == "RCPT-6401-a"
        assert claim["packaging_photo_ref"] == "PHOTO-6401-c"


class TestListingUniqueness:
    """Uniqueness is scoped to live listings on one card-and-marketplace pair."""

    def _card_with_one_live_giftbay_listing(self, client):
        """A 6000-cent ACTIVE card carrying a SUBMITTED GiftBay listing that quotes 5000 —
        deliberately wrong, so validation can later drive it to REJECTED."""
        store = create_store(
            client, name="Duplicate Listing Store", region_code="MW", address_line="36 Dup Dr"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-DL", expected_card_count=6
        )
        built = funded_physical_card(client, 6000, store=store, rack=rack)
        partner = make_reseller_partner_headers("partner-65")
        listing = submit_listing(
            client,
            built["card"]["id"],
            5000,
            "GiftBay",
            headers=partner,
            asking_price_cents=4500,
        )
        return {"card_id": built["card"]["id"], "listing": listing, "partner": partner}

    def test_a_second_live_listing_on_the_same_pair_is_refused(self, client):
        """"The listing is created in state `SUBMITTED`, with `reseller_partner_id` recorded
        from the submitting partner's `X-User-ID` — an opaque operator identifier and
        explicitly not a foreign key to any entity — and with `block_reason` empty. A
        submission is refused with `ERR_DUPLICATE_LISTING` when a listing in state `SUBMITTED`
        or `VALIDATED` already exists for the same combination of card and marketplace name; a
        previously rejected or blocked listing does not block a fresh attempt."

        Design: Corner/validations/second_live_listing_for_same_card_and_marketplace_is_rejected
        """
        world = self._card_with_one_live_giftbay_listing(client)
        assert world["listing"]["state"] == "SUBMITTED"

        response = client.create_reseller_listing(
            reseller_listing_payload(
                world["card_id"], 6000, "GiftBay", asking_price_cents=4600
            ),
            world["partner"],
        )

        assert response.status_code == 409, response.text
        validate_error(response, ERR_DUPLICATE_LISTING, 409)

        listed = client.list_card_reseller_listings(world["card_id"], make_platform_admin_headers())
        assert total_count(listed) == 1, "the refused duplicate was not persisted"

    def test_the_same_card_on_a_different_marketplace_is_not_a_duplicate(self, client):
        """"A submission is refused with `ERR_DUPLICATE_LISTING` when a listing in state
        `SUBMITTED` or `VALIDATED` already exists for the same combination of card and
        marketplace name; a previously rejected or blocked listing does not block a fresh
        attempt."

        Design: Corner/validations/second_live_listing_for_same_card_and_marketplace_is_rejected
        """
        world = self._card_with_one_live_giftbay_listing(client)

        response = client.create_reseller_listing(
            reseller_listing_payload(
                world["card_id"], 6000, "CardVault", asking_price_cents=4700
            ),
            world["partner"],
        )

        assert response.status_code == 201, response.text
        listing = validate_success(response, 201)
        assert listing["state"] == "SUBMITTED"
        assert listing["marketplace_name"] == "CardVault"

    def test_a_rejected_listing_stops_blocking_the_pair(self, client):
        """"Otherwise, if the listing's `listed_balance_cents` is not exactly equal to the
        card's `current_balance_cents`, the listing becomes `REJECTED` with `block_reason`
        `BALANCE_MISMATCH`."
        "A submission is refused with `ERR_DUPLICATE_LISTING` when a listing in state
        `SUBMITTED` or `VALIDATED` already exists for the same combination of card and
        marketplace name; a previously rejected or blocked listing does not block a fresh
        attempt."

        Design: Corner/validations/second_live_listing_for_same_card_and_marketplace_is_rejected
        """
        world = self._card_with_one_live_giftbay_listing(client)

        submit_listing(
            client,
            world["card_id"],
            6000,
            "CardVault",
            headers=world["partner"],
            asking_price_cents=4700,
        )

        verdict = validate_listing(
            client,
            world["listing"]["id"],
            headers=make_fraud_analyst_headers("analyst-65"),
            validation_note="balance does not match",
        )
        assert verdict["state"] == "REJECTED"
        assert verdict["block_reason"] == "BALANCE_MISMATCH"

        response = client.create_reseller_listing(
            reseller_listing_payload(
                world["card_id"], 6000, "GiftBay", asking_price_cents=5800
            ),
            world["partner"],
        )

        assert response.status_code == 201, response.text
        fresh = validate_success(response, 201)
        assert fresh["state"] == "SUBMITTED"
        assert fresh["marketplace_name"] == "GiftBay"
        assert fresh["listed_balance_cents"] == 6000

        listed = client.list_card_reseller_listings(world["card_id"], make_platform_admin_headers())
        assert total_count(listed) == 3


class TestSpendableCeilingIsTheAvailableBalance:
    """The fiscal check reads available_balance_cents, not the ledger balance."""

    def _card_with_a_live_hold(self, client):
        """A 10000-cent ACTIVE card carrying one ACTIVE 4000-cent hold, so 6000 cents are
        spendable while the ledger balance is still 10000."""
        store = create_store(
            client, name="Available Balance Store", region_code="SE", address_line="37 Avail Ave"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-AB", expected_card_count=6
        )
        built = funded_physical_card(client, 10000, store=store, rack=rack)
        hold = hold_on_card(client, built["card"]["id"], 4000, minutes=360)
        return {"store": store, "card_id": built["card"]["id"], "hold": hold}

    def test_a_redemption_above_the_available_balance_is_refused(self, client):
        """"A redemption is refused when the card is not `ACTIVE` (`ERR_CARD_NOT_ACTIVE`), when
        its posture is `FROZEN` (`ERR_CARD_FROZEN`), when the merchant store's floor is
        `SUSPENDED` (`ERR_STORE_FLOOR_SUSPENDED`), and when `amount_cents` exceeds the card's
        `available_balance_cents` (`ERR_INSUFFICIENT_BALANCE`) — in exactly that order of
        precedence. The spendable ceiling is the *available* balance, not the current one, so
        outstanding holds genuinely reduce what may be spent."

        Design: Corner/validations/redemption_above_available_balance_is_rejected
        """
        world = self._card_with_a_live_hold(client)
        assert world["hold"]["state"] == "ACTIVE"

        before = read_card(client, world["card_id"])
        assert before["current_balance_cents"] == 10000
        assert before["available_balance_cents"] == 6000

        response = client.create_redemption(
            world["card_id"],
            redemption_payload(7000, world["store"]["id"], pos_terminal_id="T-66"),
            make_pos_associate_headers(),
        )

        assert response.status_code == 422, response.text
        validate_error(response, ERR_INSUFFICIENT_BALANCE, 422)

        events = client.list_ledger_events(
            make_platform_admin_headers(),
            {"card_id": world["card_id"], "type": "REDEMPTION"},
        )
        assert total_count(events) == 0, "the refused redemption appended nothing"

    def test_a_redemption_exactly_at_the_available_balance_is_accepted(self, client):
        """"The debit kinds, whose `signed_amount_cents` is the negated amount, are
        `REDEMPTION`, `REISSUE_DEBIT` and `REISSUE_CREDIT_REVERSAL`."
        "`held_amount_cents` is the sum of the amounts of the counted holds, and
        `available_balance_cents` is the current balance minus the held amount, floored at
        zero."
        "Whenever an append or a reversal leaves an `ACTIVE` card's re-derived
        `current_balance_cents` at exactly zero, the card transitions `ACTIVE → DEPLETED` and
        its `version` increments."

        Design: Corner/validations/redemption_above_available_balance_is_rejected
        """
        world = self._card_with_a_live_hold(client)

        response = client.create_redemption(
            world["card_id"],
            redemption_payload(6000, world["store"]["id"], pos_terminal_id="T-66"),
            make_pos_associate_headers(),
        )

        assert response.status_code == 201, response.text
        event = validate_success(response, 201)
        assert event["amount_cents"] == 6000

        stored = validate_success(
            client.get_ledger_event(event["id"], make_platform_admin_headers())
        )
        assert stored["signed_amount_cents"] == -6000

        card = read_card(client, world["card_id"])
        assert card["current_balance_cents"] == 4000
        assert card["held_amount_cents"] == 4000
        assert card["available_balance_cents"] == 0
        assert card["activation_state"] == "ACTIVE"

        hold = validate_success(
            client.get_redemption_hold(world["hold"]["id"], make_platform_admin_headers())
        )
        assert hold["state"] == "ACTIVE", "the redemption did not consume the hold"


class TestReissueCapIsTestedOnTheGross:
    """The per-claim cap is measured on the gross recovery, before the claimant ceiling."""

    def _claim_whose_gross_exceeds_the_cap(self, client):
        """A 200000-cent card drained by one 150000-cent redemption, with a fully evidenced
        claim for the whole drained amount and an OPEN period to receive the write-off."""
        store = create_store(
            client, name="Reissue Cap Store", region_code="NW", address_line="38 Cap Ct"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-RC", expected_card_count=6
        )
        period = open_period(client, label="2026-08 reissue cap")
        built = funded_physical_card(client, 200000, store=store, rack=rack)
        redeem(
            client,
            built["card"]["id"],
            150000,
            store["id"],
            pos_terminal_id="T-67",
            memo="drained in one shot",
        )
        claim = file_claim(
            client,
            built["card"]["id"],
            disputed_amount_cents=150000,
            purchased_at=CLOCK_ORIGIN,
            headers=make_fraud_analyst_headers("analyst-67"),
            claimant_name="Hugo Melnyk",
            claimant_contact="hugo@example.test",
            purchase_receipt_ref="RCPT-6701",
            packaging_photo_ref="PHOTO-6701",
        )
        return {
            "store": store,
            "period": period,
            "card_id": built["card"]["id"],
            "claim": claim,
        }

    def test_an_approval_whose_gross_exceeds_the_cap_is_refused(self, client):
        """"Third, the cap is tested before any other clamping: an approval whose
        `gross_reissue_cents` exceeds `reissue_cap_cents` is refused with
        `ERR_REISSUE_LIMIT_EXCEEDED`, nothing at all is written, and the claim stays in
        `SUBMITTED`. The comparison is strict, so a gross landing exactly on the cap is payable
        while one cent above it is not."

        Design: Corner/validations/claim_gross_reissue_above_the_cap_is_rejected
        """
        world = self._claim_whose_gross_exceeds_the_cap(client)

        response = client.decide_victim_claim(
            world["claim"]["id"],
            claim_decision_payload("APPROVE", decision_note="gross recovery exceeds the cap"),
            make_risk_manager_headers("risk-67"),
        )

        assert response.status_code == 422, response.text
        validate_error(response, ERR_REISSUE_LIMIT_EXCEEDED, 422)

        claim = read_claim(client, world["claim"]["id"])
        assert claim["state"] == "SUBMITTED"
        assert claim["version"] == world["claim"]["version"]
        assert not claim["gross_reissue_cents"], "nothing at all is written"
        assert not claim["reissue_amount_cents"]
        assert not claim["residual_transfer_cents"]
        assert not claim["reissued_card_id"]

    def test_the_refused_approval_mints_no_card_and_books_no_writeoff(self, client):
        """"Third, the cap is tested before any other clamping: an approval whose
        `gross_reissue_cents` exceeds `reissue_cap_cents` is refused with
        `ERR_REISSUE_LIMIT_EXCEEDED`, nothing at all is written, and the claim stays in
        `SUBMITTED`."
        "While a period is `OPEN` it accumulates nothing except writeoffs:
        `unauthorized_writeoff_cents` is the running total of `reissue_amount_cents` credited by
        approved victim claims whose approval landed inside its span, decremented again when
        such a claim is rescinded, and it is the **only** field the claim cascade of §3.9 ever
        touches on a period."

        Design: Corner/validations/claim_gross_reissue_above_the_cap_is_rejected
        """
        world = self._claim_whose_gross_exceeds_the_cap(client)

        client.decide_victim_claim(
            world["claim"]["id"],
            claim_decision_payload("APPROVE", decision_note="gross recovery exceeds the cap"),
            make_risk_manager_headers("risk-67"),
        )

        card = read_card(client, world["card_id"])
        assert card["activation_state"] == "ACTIVE"
        assert card["current_balance_cents"] == 50000
        assert not card["closed_at"]

        replacements = client.list_gift_cards(
            make_platform_admin_headers(), {"reissued_from_card_id": world["card_id"]}
        )
        assert total_count(replacements) == 0, "no replacement card was minted"

        period = read_period(client, world["period"]["id"])
        assert period["unauthorized_writeoff_cents"] == 0
        assert period["state"] == "OPEN"

        events = client.list_ledger_events(
            make_platform_admin_headers(), {"card_id": world["card_id"]}
        )
        assert total_count(events) == 2, "the activation load and the one redemption only"


class TestWellformednessPrecedesTheParentLookup:
    """A body that is malformed and also names an absent parent yields the body error."""

    def test_the_malformed_field_is_reported_rather_than_the_absent_store(self, client):
        """"Every request is validated as an ordered ladder, and **the first violation
        encountered wins**: the request is rejected with that rule's error and no later rule is
        evaluated."
        "`expected_card_count`, `observed_card_count` and `seal_breaks_observed` must each be at
        least 0 ... Any failure is `ERR_INVALID_REQUEST` (400)."
        "Every `store_id`, `rack_id`, `card_id`, `alert_id` and `liability_period_id` supplied on
        a request must resolve to a live row, failing `ERR_STORE_NOT_FOUND`,
        `ERR_RACK_NOT_FOUND`, `ERR_CARD_NOT_FOUND`, `ERR_ALERT_NOT_FOUND` or
        `ERR_PERIOD_NOT_FOUND` (404) respectively."

        Design: Corner/validations/wellformedness_check_precedes_the_parent_lookup
        """
        create_store(
            client, name="Cascade Order Store", region_code="MW", address_line="39 Cascade Cir"
        )

        response = client.create_card_rack(
            card_rack_payload(
                ABSENT_UUID, rack_label="RACK-BAD", expected_card_count=-1
            ),
            make_platform_admin_headers(),
        )

        assert response.status_code == 400, response.text
        body = validate_error(response, ERR_INVALID_REQUEST, 400)
        assert body["error_id"] != ERR_STORE_NOT_FOUND, "the FK was never resolved"

    def test_the_rejected_rack_is_not_created_and_the_real_store_is_untouched(self, client):
        """"A rack belongs to exactly one store", and a rejected request "is not a mutation", so
        no rack row appears.
        "A store opens at `OPEN`."

        Design: Corner/validations/wellformedness_check_precedes_the_parent_lookup
        """
        store = create_store(
            client, name="Cascade Order Store", region_code="MW", address_line="39 Cascade Cir"
        )

        client.create_card_rack(
            card_rack_payload(
                ABSENT_UUID, rack_label="RACK-BAD", expected_card_count=-1
            ),
            make_platform_admin_headers(),
        )

        racks = client.list_card_racks(make_platform_admin_headers())
        assert total_count(racks) == 0

        assert read_store(client, store["id"])["floor_posture"] == "OPEN"
