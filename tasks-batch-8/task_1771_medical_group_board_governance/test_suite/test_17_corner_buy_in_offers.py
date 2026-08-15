"""Corner queue: buy-in offer pricing floor, completion side effects, payment gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_buy_in_offer,
    create_buy_in_offer_payload,
    create_physician,
    create_policy,
    get_buy_in_offer,
    get_physician,
    make_physician_headers,
    pay_installment,
    respond_offer,
    set_clock,
    validate_error,
)


class TestBuyInOfferMinFloorBindingInJune:
    def test_floor_binds_over_tiny_proration(self, api):
        """PRD §3.2: "Proration works in twelfths of the fiscal year: the fiscal month
        index counts months from the fiscal year start, so an offer made in July (the
        fiscal year start under the default `fiscal_year_start_month` of 7) has
        `proration_twelfths` of 12 and an offer made in June has `proration_twelfths`
        of 1."
        PRD §3.2: "`final_amount_cents` is the prorated amount, but never below
        `min_buy_in_cents`."
        June offer for a 0-tenure associate: round(10000000 * 1/12) = 833333, floored
        to 5000000.

        Design: Corner/entities/buy_in_offer_min_floor_binding_in_june
        """
        create_policy(total_shares_authorized=1000000)
        set_clock("2027-06-01T00:00:00Z")
        p = create_physician(full_name="Dr J", hire_date="2027-05-01T00:00:00Z")
        offer = create_buy_in_offer(p["id"], target_tier="PARTNER_TRACK",
                                    share_grant=0, installment_count=1)
        assert offer["proration_twelfths"] == 1
        assert offer["discount_pct_applied"] == pytest.approx(0.0)
        assert offer["final_amount_cents"] == 5000000, (
            f"the min_buy_in_cents floor binds over raw 833333, got {offer['final_amount_cents']}"
        )


class TestBuyInCompletionAdvancesTier:
    def test_final_installment_completes_and_advances(self, api):
        """PRD §3.2: "When the final installment lands — `paid_installment_count`
        reaching `installment_count` — the offer completes, and the physician's tier
        advances: to `PARTNER_TRACK` with no shares issued for a partner-track offer"
        PRD §3.2: "The `installment_schedule_cents` splits the final amount into
        `installment_count` equal parts by flooring, with the remainder cents placed on
        the first installment"
        P hired 2024-01-01 offered at the default clock: tenure 2 -> 8800000 split into
        two installments of 4400000.

        Design: Corner/state_machines/buy_in_completion_advances_tier_and_stamps_schedule
        """
        create_policy(total_shares_authorized=1000000)
        p = create_physician(full_name="Dr P", hire_date="2024-01-01T00:00:00Z")
        offer = create_buy_in_offer(p["id"], target_tier="PARTNER_TRACK",
                                    share_grant=0, installment_count=2)
        assert offer["installment_schedule_cents"] == [4400000, 4400000]

        respond_offer(offer["id"], p, "ACCEPT")
        after_first = pay_installment(offer["id"], 4400000, physician=p)
        assert after_first["paid_installment_count"] == 1
        assert after_first["status"] == "ACCEPTED"

        after_second = pay_installment(offer["id"], 4400000)
        assert after_second["status"] == "COMPLETED"
        assert after_second["paid_installment_count"] == 2

        physician = get_physician(p["id"])
        assert physician["partnership_status"] == "PARTNER_TRACK"
        assert physician["shares_held"] == 0, "PARTNER_TRACK carries no voting shares"


class TestInstallmentExactAmountAndAcceptedGate:
    def test_pay_before_accept_and_wrong_amount_rejected(self, api):
        """PRD §3.2: "Each installment payment carries `amount_cents` and must equal
        the scheduled installment amount exactly; anything else is rejected with
        `ERR_INSTALLMENT_AMOUNT_MISMATCH`. The offer must be `ACCEPTED` to accept
        payment, otherwise `ERR_OFFER_NOT_OPEN`."

        Design: Corner/validations/installment_exact_amount_and_accepted_gate
        """
        create_policy(total_shares_authorized=1000000)
        p = create_physician(full_name="Dr P", hire_date="2024-01-01T00:00:00Z")
        offer = create_buy_in_offer(p["id"], target_tier="PARTNER_TRACK",
                                    share_grant=0, installment_count=2)
        p_headers = make_physician_headers(p["id"])

        resp = api_client.pay_installment(
            offer["id"], {"amount_cents": 4400000}, p_headers
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_OPEN)

        respond_offer(offer["id"], p, "ACCEPT")
        resp = api_client.pay_installment(
            offer["id"], {"amount_cents": 4400001}, p_headers
        )
        validate_error(resp, ApiErrorId.ERR_INSTALLMENT_AMOUNT_MISMATCH)
        assert get_buy_in_offer(offer["id"])["paid_installment_count"] == 0


class TestOwnershipOtherPhysicianOfferForbidden:
    def test_physician_cannot_respond_to_anothers_offer(self, api):
        """PRD §2.1: "A physician caller may act only on their own offers, their own
        votes, their own disclosures, their own exit valuation, and their own
        assessments; acting on a resource owned by another physician is rejected with
        `ERR_RESOURCE_OWNERSHIP` (HTTP 403)."

        Design: Corner/validations/ownership_other_physician_offer_forbidden
        """
        create_policy(total_shares_authorized=1000000)
        p1 = create_physician(full_name="Dr P1", hire_date="2024-01-01T00:00:00Z")
        p2 = create_physician(full_name="Dr P2", hire_date="2024-02-01T00:00:00Z")
        offer = create_buy_in_offer(p1["id"], target_tier="PARTNER_TRACK",
                                    share_grant=0, installment_count=1)
        resp = api_client.respond_buy_in_offer(
            offer["id"], {"decision": "ACCEPT"}, make_physician_headers(p2["id"])
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_OWNERSHIP)
        assert get_buy_in_offer(offer["id"])["status"] == "OFFERED"


class TestBodyFkReferenceNotFound:
    def test_offer_for_nonexistent_physician_rejected(self, api):
        """PRD §2.7: "Fifth, existence: path identifiers are validated left to right,
        and foreign keys referenced in the body must resolve (`ERR_NOT_FOUND`)."

        Design: Corner/validations/body_fk_reference_not_found
        """
        create_policy(total_shares_authorized=1000000)
        resp = api_client.create_buy_in_offer(
            create_buy_in_offer_payload(NON_EXISTENT_UUID),
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
