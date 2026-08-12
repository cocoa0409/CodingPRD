"""Sutler row: dual-variant booth fee (provisional vs final settlement),
multi-branch fee formula (discount / floor / late surcharge), and the
settlement gates with their category ordering."""
from test_helpers import (
    TEST_USERS,
    api_client,
    ApiErrorId,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_AGREEMENT_LAPSED,
    CLOCK_LATE_INSURANCE,
    CLOCK_ON_TIME_INSURANCE,
    CLOCK_SETTLEMENT_IN_FORCE,
)
from test_helpers.fixtures import (
    add_signed_agreement,
    approve_vendor,
    complete_event,
    contract_vendor,
    create_event,
    create_vendor,
    open_gates,
    open_registration,
    publish_event,
    set_clock,
    setup_approved_vendor,
    setup_registration_open_event,
)
from test_helpers.test_users import make_vendor_headers

ORG = TEST_USERS["organizer_headers"]


class TestDualVariantFee:
    def test_vendor_provisional_fee_vs_final_settlement(self, api):
        """PRD §3.8: "Settlement computes `final_fee_cents` with the same base,
        multi-day discount, and floor as the provisional fee, and then — because
        the certificate's arrival is now known — adds the event's flat
        `vendor_late_insurance_surcharge_cents` when `insurance_uploaded_at`
        falls strictly after the event's `vendor_insurance_deadline_at`"
        PRD §3.8: "The `balance_due_cents` is fixed at settlement as
        `final_fee_cents` minus `fee_paid_cents`"

        Design: Difficulty/dual_variant_calc/vendor_provisional_fee_vs_final_settlement
        """
        event = create_event()
        set_clock(CLOCK_LATE_INSURANCE)  # 2026-07-02, after the 2026-07-01 deadline
        add_signed_agreement(event["id"], "LANDOWNER_USE")
        add_signed_agreement(event["id"], "INSURANCE_LIABILITY")
        open_registration(event["id"])

        vendor = setup_approved_vendor(event["id"], frontage_feet=20, requested_days=3)
        assert vendor["provisional_fee_cents"] == 48600, (
            "provisional variant: max(round_half_up(20*3*900*0.9), 5000)"
        )
        contracted = contract_vendor(vendor["id"], fee_payment_cents=48600)
        assert contracted["status"] == "CONTRACTED"

        publish_event(event["id"])
        open_gates(event["id"])
        complete_event(event["id"])

        settled = validate_success(api_client.settle_vendor(vendor["id"], ORG), 200)
        assert settled["status"] == "SETTLED"
        assert settled["provisional_fee_cents"] == 48600
        assert settled["final_fee_cents"] == 51100, (
            "final variant adds the 2500 late-insurance surcharge"
        )
        assert settled["balance_due_cents"] == 2500

    def test_vendor_fee_equal_when_insurance_exactly_at_deadline(self, api):
        """PRD §3.8: "identical inputs therefore produce a higher final fee when
        the insurance was late, while a certificate arriving exactly at the
        deadline escapes the surcharge"
        PRD §2.7: "The sutler late-insurance boundary is strict: a certificate
        uploaded exactly at the deadline does not incur the surcharge."

        Design: Difficulty/dual_variant_calc/vendor_provisional_fee_vs_final_settlement
        """
        event = create_event()
        add_signed_agreement(event["id"], "LANDOWNER_USE")
        add_signed_agreement(event["id"], "INSURANCE_LIABILITY")
        open_registration(event["id"])
        vendor = setup_approved_vendor(event["id"], frontage_feet=20, requested_days=3)
        set_clock("2026-07-01T00:00:00Z")  # exactly the deadline: not strictly after
        contract_vendor(vendor["id"], fee_payment_cents=48600)
        publish_event(event["id"])
        open_gates(event["id"])
        complete_event(event["id"])
        set_clock(CLOCK_SETTLEMENT_IN_FORCE)

        settled = validate_success(api_client.settle_vendor(vendor["id"], ORG), 200)
        assert settled["final_fee_cents"] == 48600, (
            "exactly-at-deadline insurance escapes the surcharge (strict >)"
        )
        assert settled["final_fee_cents"] == settled["provisional_fee_cents"]
        assert settled["balance_due_cents"] == 0


class TestFeeFormulaBranches:
    def test_vendor_fee_discount_branch(self, api):
        """PRD §3.8: "Approval computes `provisional_fee_cents`: the base fee is
        `frontage_feet` multiplied by `requested_days` multiplied by the event's
        `vendor_frontage_rate_cents`; when `requested_days` is at least three,
        the base is reduced by the `vendor_multi_day_discount_pct` fraction and
        rounded half-up to whole cents; and the fee is the greater of that base
        and the event's `vendor_min_fee_cents`."

        Design: Difficulty/combinatorial_formula/vendor_fee_multibranch_floor_discount_surcharge
        """
        event = setup_registration_open_event()
        vendor = create_vendor(event["id"], business_name="Sutler Sam",
                               frontage_feet=20, requested_days=3)
        approved = approve_vendor(vendor["id"])
        # max(round_half_up(20 * 3 * 900 * 0.9), 5000) = max(48600, 5000)
        assert approved["provisional_fee_cents"] == 48600, "multi-day discount branch"

    def test_vendor_fee_floor_branch(self, api):
        """PRD §3.8: "the fee is the greater of that base and the event's
        `vendor_min_fee_cents`. The provisional fee never includes the
        late-insurance surcharge, since no certificate is yet due."

        Design: Difficulty/combinatorial_formula/vendor_fee_multibranch_floor_discount_surcharge
        """
        event = setup_registration_open_event()
        vendor = create_vendor(event["id"], business_name="Tiny Tina",
                               wares_description="Ribbon and lace",
                               frontage_feet=3, requested_days=1)
        approved = approve_vendor(vendor["id"])
        # 3 * 1 * 900 = 2700 < 5000 -> floor applies.
        assert approved["provisional_fee_cents"] == 5000, "min-fee floor branch"


class TestSettlementGates:
    def _setup_completed_contracted_vendor(self, payment_cents, contract_clock=None):
        """CONTRACTED vendor on a COMPLETED event; landowner window
        2026-07-01..2026-07-31. Returns (event, vendor)."""
        event = create_event()
        add_signed_agreement(event["id"], "LANDOWNER_USE")
        add_signed_agreement(event["id"], "INSURANCE_LIABILITY")
        open_registration(event["id"])
        vendor = setup_approved_vendor(event["id"], frontage_feet=20, requested_days=3)
        if contract_clock:
            set_clock(contract_clock)
        contract_vendor(vendor["id"], fee_payment_cents=payment_cents)
        publish_event(event["id"])
        open_gates(event["id"])
        complete_event(event["id"])
        return event, vendor

    def test_settle_with_outstanding_balance_rejected(self, api):
        """PRD §3.8: "`fee_paid_cents` must be at least `provisional_fee_cents`,
        else `ERR_VENDOR_BALANCE_OUTSTANDING`"

        Design: Corner/validations/settle_with_outstanding_balance_rejected
        """
        event, vendor = self._setup_completed_contracted_vendor(payment_cents=0)
        set_clock(CLOCK_SETTLEMENT_IN_FORCE)  # landowner agreement in force

        resp = api_client.settle_vendor(vendor["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_VENDOR_BALANCE_OUTSTANDING, 409)
        reread = validate_success(
            api_client.get_vendor(vendor["id"], make_vendor_headers(vendor["id"])), 200
        )
        assert reread["status"] == "CONTRACTED", "rejected settlement changes nothing"

    def test_vendor_settlement_on_time_insurance_keeps_provisional(self, api):
        """PRD §3.8: "identical inputs therefore produce a higher final fee when
        the insurance was late, while a certificate arriving exactly at the
        deadline escapes the surcharge"
        PRD §3.8: "The `balance_due_cents` is fixed at settlement as
        `final_fee_cents` minus `fee_paid_cents`, and the vendor moves to
        `SETTLED`."

        Design: Corner/calculations/vendor_settlement_on_time_insurance_keeps_provisional
        """
        event, vendor = self._setup_completed_contracted_vendor(
            payment_cents=48600, contract_clock=CLOCK_ON_TIME_INSURANCE
        )
        set_clock(CLOCK_SETTLEMENT_IN_FORCE)

        settled = validate_success(api_client.settle_vendor(vendor["id"], ORG), 200)
        assert settled["final_fee_cents"] == 48600, (
            "on-time insurance: final variant equals the provisional fee"
        )
        assert settled["balance_due_cents"] == 0
        assert settled["status"] == "SETTLED"

    def test_vendor_settle_referential_error_beats_fiscal_error(self, api):
        """PRD §2.9: "eighth, agreement-in-force referential checks; and ninth,
        fiscal and capacity checks (insurance sufficiency, vendor balance,
        parking and area capacity)"
        PRD §3.8: "a `SIGNED` `LANDOWNER_USE` agreement must be in force at
        settlement time — logical now within its inclusive window — else
        `ERR_AGREEMENT_NOT_IN_FORCE`; and `fee_paid_cents` must be at least
        `provisional_fee_cents`, else `ERR_VENDOR_BALANCE_OUTSTANDING`."

        Design: Difficulty/priority_pair_validation_conflict/vendor_settle_referential_error_beats_fiscal_error
        """
        event, vendor = self._setup_completed_contracted_vendor(payment_cents=0)
        set_clock(CLOCK_AGREEMENT_LAPSED)  # 2026-08-02: window ended 2026-07-31

        resp = api_client.settle_vendor(vendor["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_IN_FORCE, 409)

    def test_vendor_settle_referential_error_applies_no_change(self, api):
        """PRD §2.9: "eighth, agreement-in-force referential checks; and ninth,
        fiscal and capacity checks (insurance sufficiency, vendor balance,
        parking and area capacity)"
        PRD §2.9: "a request failing an earlier category never surfaces a later
        category's error"

        Design: Difficulty/priority_pair_validation_conflict/vendor_settle_referential_error_beats_fiscal_error
        """
        event, vendor = self._setup_completed_contracted_vendor(payment_cents=0)
        set_clock(CLOCK_AGREEMENT_LAPSED)

        resp = api_client.settle_vendor(vendor["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_IN_FORCE, 409)
        reread = validate_success(
            api_client.get_vendor(vendor["id"], make_vendor_headers(vendor["id"])), 200
        )
        assert reread["status"] == "CONTRACTED"
        assert reread["final_fee_cents"] is None, "no settlement is computed"
        assert reread["balance_due_cents"] is None
        assert reread["fee_paid_cents"] == 0


class TestContractingGate:
    def test_contract_before_approval_rejected(self, api):
        """PRD §3.8: "Approval is an organizer action valid only from `APPLIED`
        (`ERR_INVALID_VENDOR_STATUS`)"
        PRD §3.8: "Contracting belongs to the vendor themself — the caller's
        `X-User-ID` must equal `owner_user_id` (`ERR_FORBIDDEN`) — from
        `APPROVED`, while the event is in `REGISTRATION_OPEN` or `PUBLISHED`
        (`ERR_INVALID_EVENT_POSTURE`)."

        Design: Corner/state_machines/contract_before_approval_rejected
        """
        event = setup_registration_open_event()
        vendor = create_vendor(event["id"], frontage_feet=10, requested_days=2)
        assert vendor["status"] == "APPLIED"
        resp = api_client.contract_vendor(
            vendor["id"],
            {"insurance_cert_ref": "CERT-1", "fee_payment_cents": 18000},
            make_vendor_headers(vendor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_VENDOR_STATUS, 409)
        reread = validate_success(
            api_client.get_vendor(vendor["id"], make_vendor_headers(vendor["id"])), 200
        )
        assert reread["status"] == "APPLIED"
