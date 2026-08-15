"""Estate recovery: death recording, provisional vs final claim, filing deadline, payments (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_estate_case,
    factories,
    get_estate_case,
    get_estate_case_for_member,
    mark_member_deceased,
    set_clock,
    setup_estate_claim_filed,
    setup_estate_opened,
    setup_posted_recovery,
    validate_error,
    validate_paginated,
    validate_success,
)

ACCT = TEST_USERS["accountant_headers"]
ERO = TEST_USERS["estate_officer_headers"]


class TestMarkDeceased:
    def test_mark_deceased_opens_estate_case_with_provisional_defaults(self, api):
        """PRD §3.6: "The member moves from `ACTIVE` to `DECEASED`, both supplied values are recorded on the member, and the member's `version` increments by one."
        PRD §3.6: "At opening the claim is provisional: `provisional_claim_cents` equals the `lifetime_paid_cents` in full, with no offsets — a conservative upper bound used for the probate notice. The final `claim_amount_cents` remains null until the claim is filed, `claim_outstanding_cents` is zero while the case is `OPENED`, `total_paid_cents` starts at zero, and `probate_case_number` and `exempt_services_cents` are null until captured at filing."

        Design: Corner/entities/estate_case_created_with_provisional_defaults
        """
        ctx = setup_estate_opened(
            date_of_death="2026-03-01", lifetime_paid_cents=750000
        )
        member = ctx["member"]
        assert member["status"] == "DECEASED"
        assert member["date_of_death"] == "2026-03-01"
        estate_case = ctx["estate_case"]
        assert_estate_case(estate_case)
        assert estate_case["status"] == "OPENED"
        assert estate_case["provisional_claim_cents"] == 750000
        assert estate_case["total_paid_cents"] == 0
        assert estate_case["claim_outstanding_cents"] == 0
        assert estate_case["claim_amount_cents"] is None
        assert estate_case["probate_case_number"] is None
        assert estate_case["exempt_services_cents"] is None

    def test_double_mark_deceased_rejected(self, api):
        """PRD §3.6: "The member must not already have an estate case; a second recording is rejected with `ERR_ESTATE_CASE_EXISTS` (HTTP 409)."

        Design: Corner/validations/double_mark_deceased_rejected
        """
        ctx = setup_estate_opened(
            date_of_death="2026-02-01", lifetime_paid_cents=500000
        )
        member_id = ctx["member"]["id"]
        resp = api.mark_deceased(
            member_id,
            factories.mark_deceased_payload(
                date_of_death="2026-02-01", lifetime_paid_cents=500000
            ),
            ERO,
        )
        validate_error(resp, ApiErrorId.ERR_ESTATE_CASE_EXISTS)
        data, meta = validate_paginated(
            api.list_estate_cases(ERO, params={"member_id": member_id})
        )
        assert meta["total_count"] == 1


class TestProvisionalVsFinalClaim:
    def test_provisional_claim_ignores_tpl_offsets(self, api):
        """PRD §3.6: "At opening the claim is provisional: `provisional_claim_cents` equals the `lifetime_paid_cents` in full, with no offsets — a conservative upper bound used for the probate notice."

        Design: Difficulty/dual_variant_calc/estate_claim_provisional_vs_final
        """
        # Resolve a TPL case for 200000 POSTED, then mark the member deceased
        # with lifetime_paid 500000: the provisional claim stays 500000.
        tpl = setup_posted_recovery(
            posting_amount=200000, claims=[("2026-01-10", 200000)]
        )
        member_id = tpl["member"]["id"]
        mark_member_deceased(
            member_id, date_of_death="2026-03-01", lifetime_paid_cents=500000
        )
        estate_case = get_estate_case_for_member(member_id)
        assert estate_case["provisional_claim_cents"] == 500000, (
            f"Provisional claim is the gross lifetime paid amount, got {estate_case['provisional_claim_cents']}"
        )
        assert estate_case["status"] == "OPENED"
        assert estate_case["claim_amount_cents"] is None

    def test_final_claim_nets_tpl_recoveries_and_exemptions(self, api):
        """PRD §3.6: "First, the TPL offset is computed as the sum of `gross_recovery_cents` over all `POSTED` recovery postings whose settlement belongs to a TPL case of this member — dollars the program has already recovered from liable third parties. Second, `claim_amount_cents` is the `lifetime_paid_cents` less that TPL offset and less `exempt_services_cents`, floored at zero. The `claim_outstanding_cents` is set equal to the `claim_amount_cents`, an `ESTATE_CLAIM_NOTICE` is queued to the member's estate per §2.11, and the case moves to `CLAIM_FILED`."

        Design: Difficulty/dual_variant_calc/estate_claim_provisional_vs_final
        """
        # 500000 lifetime - 200000 POSTED TPL recovery - 50000 exempt = 250000.
        tpl = setup_posted_recovery(
            posting_amount=200000, claims=[("2026-01-10", 200000)]
        )
        member_id = tpl["member"]["id"]
        mark_member_deceased(
            member_id, date_of_death="2026-03-01", lifetime_paid_cents=500000
        )
        estate_case = get_estate_case_for_member(member_id)
        filed = validate_success(
            api.file_estate_claim(
                estate_case["id"],
                factories.file_claim_payload(
                    probate_case_number="P-100", exempt_services_cents=50000
                ),
                ERO,
            ),
            200,
        )
        assert filed["claim_amount_cents"] == 250000, (
            f"Final claim = 500000 - 200000 - 50000, got {filed['claim_amount_cents']}"
        )
        assert filed["claim_outstanding_cents"] == 250000
        assert filed["status"] == "CLAIM_FILED"


class TestFilingDeadline:
    def test_file_claim_on_deadline_date_succeeds(self, api):
        """PRD §3.6: "The statute allows three hundred sixty-five days: the current calendar date must be on or before the date three hundred sixty-five days after the `date_of_death`. A filing attempted later moves the estate case from `OPENED` to `TIME_BARRED` and is rejected with `ERR_ESTATE_FILING_LATE` (HTTP 409)."

        Design: Corner/state_machines/estate_filing_deadline_time_barred
        """
        # date_of_death 2026-01-01 -> deadline 2027-01-01 (inclusive).
        ctx = setup_estate_opened(
            date_of_death="2026-01-01", lifetime_paid_cents=100000
        )
        set_clock("2027-01-01T00:00:00Z")
        filed = validate_success(
            api.file_estate_claim(
                ctx["estate_case"]["id"],
                factories.file_claim_payload(
                    probate_case_number="P-A", exempt_services_cents=0
                ),
                ERO,
            ),
            200,
        )
        assert filed["status"] == "CLAIM_FILED"
        assert filed["claim_amount_cents"] == 100000

    def test_file_claim_one_day_late_time_bars_case(self, api):
        """PRD §3.6: "A filing attempted later moves the estate case from `OPENED` to `TIME_BARRED` and is rejected with `ERR_ESTATE_FILING_LATE` (HTTP 409)."

        Design: Corner/state_machines/estate_filing_deadline_time_barred
        """
        ctx = setup_estate_opened(
            date_of_death="2026-01-01", lifetime_paid_cents=100000
        )
        set_clock("2027-01-02T00:00:00Z")  # one day past the 365-day deadline
        resp = api.file_estate_claim(
            ctx["estate_case"]["id"],
            factories.file_claim_payload(
                probate_case_number="P-B", exempt_services_cents=0
            ),
            ERO,
        )
        validate_error(resp, ApiErrorId.ERR_ESTATE_FILING_LATE)
        assert get_estate_case(ctx["estate_case"]["id"])["status"] == "TIME_BARRED"


class TestEstatePayments:
    def test_payment_exactly_equal_to_outstanding_auto_pays(self, api):
        """PRD §3.6: "A recorded payment raises `total_paid_cents` by `amount_cents` and lowers `claim_outstanding_cents` by the same amount."
        PRD §3.6: "When a payment — or, per §3.7, a waiver approval — drives the outstanding balance to exactly zero, the case moves automatically from `CLAIM_FILED` to `PAID`."

        Design: Corner/state_machines/estate_record_payment_exact_outstanding_auto_paid
        """
        ctx = setup_estate_claim_filed(lifetime_paid_cents=100000)
        paid = validate_success(
            api.record_estate_payment(
                ctx["estate_case"]["id"],
                factories.record_payment_payload(amount_cents=100000),
                ACCT,
            ),
            200,
        )
        assert paid["total_paid_cents"] == 100000
        assert paid["claim_outstanding_cents"] == 0
        assert paid["status"] == "PAID"

    def test_payment_above_outstanding_rejected(self, api):
        """PRD §3.6: "Each payment carries `amount_cents`, which must be greater than zero and must not exceed the current `claim_outstanding_cents`; an overpayment is rejected with `ERR_PAYMENT_EXCEEDS_OUTSTANDING` (HTTP 409)."

        Design: Corner/validations/estate_payment_above_outstanding_rejected
        """
        ctx = setup_estate_claim_filed(lifetime_paid_cents=100000)
        resp = api.record_estate_payment(
            ctx["estate_case"]["id"],
            factories.record_payment_payload(amount_cents=100001),
            ACCT,
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING)
        after = get_estate_case(ctx["estate_case"]["id"])
        assert after["claim_outstanding_cents"] == 100000
        assert after["total_paid_cents"] == 0

    def test_waiver_application_before_claim_filed_rejected(self, api):
        """PRD §3.6: "The estate case must stand at `CLAIM_FILED`; a payment — or a waiver application, §3.7 — attempted on an estate case in any other status is rejected with `ERR_CLAIM_NOT_FILED` (HTTP 409)."

        Design: Corner/validations/waiver_create_before_claim_filed_returns_error
        """
        ctx = setup_estate_opened(
            date_of_death="2026-02-01", lifetime_paid_cents=500000
        )
        resp = api.create_waiver(
            ctx["estate_case"]["id"],
            factories.waiver_payload(
                waiver_type="FULL",
                household_income_annual_cents=1000000,
                homestead_value_cents=1000000,
            ),
            ERO,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FILED)
        data, meta = validate_paginated(
            api.list_waivers(ERO, params={"estate_case_id": ctx["estate_case"]["id"]})
        )
        assert data == [] and meta["total_count"] == 0


class TestZeroFloorFinalClaim:
    def test_final_claim_floored_at_zero_auto_pays(self, api):
        """PRD §3.6: "Second, `claim_amount_cents` is the `lifetime_paid_cents` less that TPL offset and less `exempt_services_cents`, floored at zero."
        PRD §3.6: "Should the final claim compute to exactly zero, there is nothing to collect: the case passes immediately from `CLAIM_FILED` to `PAID`."

        Design: Corner/calculations/estate_final_claim_floored_at_zero
        """
        # MT member (SUBROGATION): lien 200000, costs 100000 -> cost share
        # 50000, recovery 150000 POSTED; lifetime paid 100000 -> the final
        # claim computes negative and floors to zero.
        tpl = setup_posted_recovery(
            posting_amount=150000, state_code="MT",
            claims=[("2026-01-10", 200000)],
        )
        member_id = tpl["member"]["id"]
        assert tpl["settlement"]["state_recovery_cents"] == 150000
        mark_member_deceased(
            member_id, date_of_death="2026-03-01", lifetime_paid_cents=100000
        )
        estate_case = get_estate_case_for_member(member_id)
        filed = validate_success(
            api.file_estate_claim(
                estate_case["id"],
                factories.file_claim_payload(
                    probate_case_number="P-700", exempt_services_cents=0
                ),
                ERO,
            ),
            200,
        )
        assert filed["claim_amount_cents"] == 0, (
            f"100000 - 150000 floors to zero, got {filed['claim_amount_cents']}"
        )
        assert filed["status"] == "PAID", (
            "A zero final claim passes immediately from CLAIM_FILED to PAID"
        )
