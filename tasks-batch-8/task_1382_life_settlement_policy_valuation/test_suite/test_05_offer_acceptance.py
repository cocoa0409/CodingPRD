"""Offer acceptance guards and the acceptance cascade into closing + escrow
(PRD §3.2, §3.3, §3.4, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_broker_headers, create_offer, set_clock,
    setup_case_marketed, setup_case_in_closing,
    create_license_payload, create_broker_payload, create_insured_payload,
    create_policy_payload, order_and_deliver_le, setup_case_in_underwriting,
)

ADMIN = TEST_USERS["admin_headers"]
CM = TEST_USERS["case_manager_headers"]
UW = TEST_USERS["underwriter_headers"]


class TestAcceptanceGuards:
    def test_accept_missing_disclosures_rejected_before_commission_cap(self, api):
        """PRD §3.3: "the case's `disclosures_delivered` must be true, since a
        seller cannot sign away a policy before receiving the statutory packet
        (`ERR_DISCLOSURES_INCOMPLETE`, HTTP 422)"
        PRD §2.7: "Across all rules attached to an endpoint, evaluation follows a
        fixed priority order, and the first failure determines the response"
        PRD §2.7: "8. Business-safety rules: `ERR_DISCLOSURES_INCOMPLETE`,
        `ERR_CASE_ON_COMPLIANCE_HOLD`, `ERR_STATE_LICENSE_NOT_ACTIVE`,
        `ERR_LICENSE_EXPIRING_SOON`, `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.7: "12. Business-fiscal: `ERR_ESCROW_FUNDS_MISMATCH`,
        `ERR_COMMISSION_CAP_EXCEEDED`, `ERR_PAYMENT_AMOUNT_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/accept_missing_disclosures_rejected_before_commission_cap
        """
        ctx = setup_case_marketed(with_disclosures=False, with_offer=True)
        case, offer, broker = ctx["case"], ctx["offer"], ctx["broker"]
        resp = api.accept_offer(offer["id"], {"broker_commission_bps": 700},
                                make_broker_headers(broker["id"]))
        validate_error(resp, ApiErrorId.ERR_DISCLOSURES_INCOMPLETE)
        offer_after = validate_success(api.get_offer(offer["id"], CM))
        assert offer_after["status"] == "PENDING"
        packages, _meta = validate_paginated(api.get_case_closing_package(case["id"], CM))
        assert packages == []

    def test_accept_rejected_while_case_on_compliance_hold(self, api):
        """PRD §3.3: "the case's `hold_status` must be `CLEAR`
        (`ERR_CASE_ON_COMPLIANCE_HOLD`)"
        PRD §2.8: "A case under `COMPLIANCE_HOLD` cannot accept an offer (directly
        or via counter-acceptance), cannot have its closing package approved,
        cannot have its escrow funded, and cannot have its escrow released; each of
        those attempts is rejected with `ERR_CASE_ON_COMPLIANCE_HOLD` (HTTP 409)."
        PRD §2.8: "When that governing license transitions `ACTIVE` to `SUSPENDED`
        while the case is `MARKETED` or `IN_CLOSING`, the case's `hold_status`
        moves from `CLEAR` to `COMPLIANCE_HOLD` as a direct cascade of the
        suspension."

        Design: Difficulty/priority_pair_validation_conflict/accept_missing_disclosures_rejected_before_commission_cap
        """
        ctx = setup_case_marketed(with_disclosures=True, with_offer=True)
        case, offer, broker, lic = ctx["case"], ctx["offer"], ctx["broker"], ctx["license"]
        bh = make_broker_headers(broker["id"])

        validate_success(api.suspend_license(lic["id"], TEST_USERS["compliance_headers"]))
        held = validate_success(api.get_case(case["id"], CM))
        assert held["hold_status"] == "COMPLIANCE_HOLD"

        resp = api.accept_offer(offer["id"], {"broker_commission_bps": 455}, bh)
        validate_error(resp, ApiErrorId.ERR_CASE_ON_COMPLIANCE_HOLD)
        offer_after = validate_success(api.get_offer(offer["id"], CM))
        assert offer_after["status"] == "PENDING"
        packages, _meta = validate_paginated(api.get_case_closing_package(case["id"], CM))
        assert packages == []

    def test_disclosures_gate_accept_and_packet_validation(self, api):
        """PRD §3.2: "The payload's `packet_types` must include every one of
        COMPENSATION, ALTERNATIVES, TAX, PRIVACY, and RESCISSION_RIGHTS; a missing
        type is rejected with `ERR_INVALID_REQUEST`. A valid delivery sets
        `disclosures_delivered` true and stamps `disclosures_delivered_at` with the
        clock."

        Design: Corner/endpoints/disclosures_gate_accept_and_packet_validation
        """
        ctx = setup_case_marketed(with_disclosures=False, with_offer=True)
        case, offer, broker = ctx["case"], ctx["offer"], ctx["broker"]

        resp = api.deliver_disclosures(case["id"], {"packet_types": ["COMPENSATION"]}, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        delivered = validate_success(api.deliver_disclosures(
            case["id"],
            {"packet_types": ["COMPENSATION", "ALTERNATIVES", "TAX", "PRIVACY", "RESCISSION_RIGHTS"]},
            CM,
        ))
        assert delivered["disclosures_delivered"] is True

        accepted = validate_success(api.accept_offer(
            offer["id"], {"broker_commission_bps": 300}, make_broker_headers(broker["id"])))
        assert accepted["status"] == "ACCEPTED"

    def test_commission_cap_boundary(self, api):
        """PRD §3.3: "for the direct accept, the proposed `broker_commission_bps`
        must not exceed 600 — six percent of price, the fiscal cap —
        (`ERR_COMMISSION_CAP_EXCEEDED`, HTTP 422)."

        Design: Corner/validations/commission_cap_boundary
        """
        ctx1 = setup_case_marketed(with_disclosures=True, with_offer=True)
        accepted = validate_success(api.accept_offer(
            ctx1["offer"]["id"], {"broker_commission_bps": 600},
            make_broker_headers(ctx1["broker"]["id"])))
        assert accepted["status"] == "ACCEPTED", "600 == cap is inclusive"

        ctx2 = setup_case_marketed(with_disclosures=True, with_offer=True,
                                   with_license=False,
                                   broker_overrides={"license_number": "BR-2"},
                                   policy_overrides={"policy_number": "P-2"})
        resp = api.accept_offer(ctx2["offer"]["id"], {"broker_commission_bps": 601},
                                make_broker_headers(ctx2["broker"]["id"]))
        validate_error(resp, ApiErrorId.ERR_COMMISSION_CAP_EXCEEDED)

    def test_broker_cannot_counter_other_brokers_case(self, api):
        """PRD §2.1: "When `X-User-Role` is `Broker`, `X-User-ID` is the `id` of the
        acting `Broker`; ownership checks on any resource that references a
        `Broker` (a case's `broker_id`, an insured's `created_by_broker_id`)
        compare that foreign-key field to `X-User-ID`. A violation is rejected with
        `ERR_NOT_CASE_OWNER` (HTTP 403)."

        Design: Corner/validations/broker_cannot_counter_other_brokers_case
        """
        ctx = setup_case_marketed(with_disclosures=True, with_offer=True,
                                  broker_overrides={"license_number": "BR-A", "name": "Broker A"})
        broker_b = validate_success(api.create_broker(
            create_broker_payload(name="Broker B", license_number="BR-B"), ADMIN),
            expected_status=201)
        offer = ctx["offer"]
        resp = api.counter_offer(
            offer["id"], {"counter_amount_cents": 6100000,
                          "expected_offer_version": offer["version"]},
            make_broker_headers(broker_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_CASE_OWNER)


class TestAcceptanceCascade:
    def test_offer_acceptance_closing_chain(self, api):
        """PRD §3.3: "The acceptance cascade then fires in full: the case's
        `accepted_offer_id` is set to the accepted offer and its
        `purchase_price_cents` to the offer's `effective_price_cents`; the captured
        `broker_commission_bps` is stored on the case; the case moves from
        `MARKETED` to `IN_CLOSING`; every other offer on the same case in `PENDING`
        or `COUNTERED` moves to `REJECTED`; a `ClosingPackage` is created in
        `ASSEMBLED` with its document checklist; and the package's creation
        cascades to create the case's `EscrowAccount` in `OPEN` with
        `expected_funding_cents` pre-computed (§3.5)."
        PRD §3.4: "One row is state-dependent: STATE_SUPPLEMENT is required exactly
        when the insured's `state_code` is CA or NY."
        PRD §3.5: "Its `expected_funding_cents` is the sum of three components: the
        accepted offer's effective price, a flat escrow fee of 75000 cents (seven
        hundred fifty dollars), and a servicing fee of the price times 25 basis
        points rounded half-up to cents."

        Design: Difficulty/transitive_cascade/offer_acceptance_closing_chain
        """
        ctx = setup_case_marketed(with_disclosures=True, with_offer=False)
        case, broker = ctx["case"], ctx["broker"]
        offer1 = create_offer(case, 6000000)
        offer2 = create_offer(case, 6500000)

        accepted = validate_success(api.accept_offer(
            offer1["id"], {"broker_commission_bps": 455}, make_broker_headers(broker["id"])))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["effective_price_cents"] == 6000000

        sibling = validate_success(api.get_offer(offer2["id"], CM))
        assert sibling["status"] == "REJECTED"

        case_after = validate_success(api.get_case(case["id"], CM))
        assert case_after["status"] == "IN_CLOSING"
        assert case_after["purchase_price_cents"] == 6000000
        assert case_after["broker_commission_bps"] == 455

        packages, _m = validate_paginated(api.get_case_closing_package(case["id"], CM))
        assert len(packages) == 1
        package = packages[0]
        assert package["status"] == "ASSEMBLED"
        assert len(package["documents"]) == 7, "TX insured: no STATE_SUPPLEMENT row"
        assert all(row["signed"] is False for row in package["documents"])

        escrows, _m2 = validate_paginated(api.get_case_escrow_account(case["id"], CM))
        assert len(escrows) == 1
        escrow = escrows[0]
        assert escrow["status"] == "OPEN"
        # 6000000 + 75000 + round_half_up(6000000 * 25/10000) = 6090000
        assert escrow["expected_funding_cents"] == 6090000

    def test_offer_acceptance_stamps_offer_and_case_fields(self, api):
        """PRD §3.3: "On acceptance the offer's `effective_price_cents` is fixed:
        the `counter_amount_cents` when accepted from `COUNTERED`, otherwise the
        `amount_cents`; it stays unset until the offer reaches `ACCEPTED`. The
        accepted offer's `version` increments."
        PRD §3.3: "The acceptance cascade then fires in full: the case's
        `accepted_offer_id` is set to the accepted offer and its
        `purchase_price_cents` to the offer's `effective_price_cents`; the captured
        `broker_commission_bps` is stored on the case; the case moves from
        `MARKETED` to `IN_CLOSING`; every other offer on the same case in `PENDING`
        or `COUNTERED` moves to `REJECTED`"

        Design: Difficulty/transitive_cascade/offer_acceptance_closing_chain
        """
        ctx = setup_case_marketed(with_disclosures=True, with_offer=False)
        case, broker = ctx["case"], ctx["broker"]
        offer = create_offer(case, 6000000)
        assert offer["effective_price_cents"] is None
        assert offer["version"] == 1

        accepted = validate_success(api.accept_offer(
            offer["id"], {"broker_commission_bps": 455}, make_broker_headers(broker["id"])))
        assert accepted["effective_price_cents"] == 6000000
        assert accepted["version"] == 2, "acceptance increments the offer's version"

        case_after = validate_success(api.get_case(case["id"], CM))
        assert case_after["accepted_offer_id"] == offer["id"]
        assert case_after["status"] == "IN_CLOSING"

    def test_closing_package_filter_by_offer(self, api):
        """PRD §4: "| GET | /api/closing-packages | List closing packages, optional
        `offer_id` filter |"
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/endpoints/closing_package_filter_by_offer
        """
        from test_helpers import NON_EXISTENT_UUID
        ctx = setup_case_in_closing(portfolio=False)
        packages, meta = validate_paginated(
            api.list_closing_packages(CM, params={"offer_id": ctx["offer"]["id"]}))
        assert len(packages) == 1
        assert packages[0]["offer_id"] == ctx["offer"]["id"]
        assert packages[0]["case_id"] == ctx["case"]["id"]

        empty, meta2 = validate_paginated(
            api.list_closing_packages(CM, params={"offer_id": NON_EXISTENT_UUID}))
        assert empty == []
        assert meta2["total_count"] == 0
