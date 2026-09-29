"""Refusals on the funding side: certification, registration, cash and recoupment."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_assessment,
    assert_member_assessment,
    assert_member_insurer,
    certify_assessment,
    draft_assessment,
    file_surcharge,
    get_success_data,
    list_member_assessments,
    member_insurer_payload,
    member_payment_payload,
    read_assessment,
    read_insolvency,
    read_member_assessment,
    recoupment_remittance_payload,
    register_member_insurer,
    setup_certified_assessment,
    setup_member_assessment_with_surcharge,
    setup_triggered_insolvency,
    surcharge_filing_payload,
    validate_error,
)

ADMIN = TEST_USERS["association_admin_headers"]
ASSESSOR = TEST_USERS["assessment_officer_headers"]

LIVE_TERM = {
    "policy_number": "PA-1001",
    "policyholder_name": "Ada Renner",
    "effective_date": "2025-10-01",
    "expiration_date": "2026-10-01",
    "annual_premium_cents": 1_200_000,
}
SMALL_BASE_MEMBER = [
    {
        "naic_code": "20001",
        "insurer_name": "Huron Standard Insurance",
        "direct_written_premium_cents": 10_000_000,
    }
]
LARGE_BASE_MEMBER = [
    {
        "naic_code": "20001",
        "insurer_name": "Huron Standard Insurance",
        "direct_written_premium_cents": 60_000_000,
    }
]
HURON_2025 = {
    "naic_code": "20001",
    "insurer_name": "Huron Standard Insurance",
    "assessable_line": "PERSONAL_AUTO",
    "base_year": 2025,
    "direct_written_premium_cents": 10_000_000,
}


class TestCertificationGates:
    """Certification runs once, and only over a pool that actually wrote premium."""

    def test_certifying_an_already_certified_levy_is_refused(self):
        """Certification is where the allocation happens, and it is admissible only while the
        assessment is in `DRAFT` and the governing insolvency file is in `TRIGGERED`, a `DECLARED`
        file being refused with `ERR_INSOLVENCY_NOT_TRIGGERED`.

        The target assessment's `status` is `DRAFT` → `ERR_ASSESSMENT_INVALID_STATE` (HTTP 409), on
        `POST /assessments/{id}/certify`.

        Design: Corner/validations/certifying_an_already_certified_assessment_is_refused
        """
        env = setup_certified_assessment(
            member_specs=SMALL_BASE_MEMBER,
            needed_amount_cents=150_000,
            policy_overrides=dict(LIVE_TERM),
        )
        assessment = env["assessment"]
        assert assessment["status"] == "CERTIFIED", assessment["status"]
        assert assessment["member_count"] == 1, assessment["member_count"]

        validate_error(
            api_client.certify_assessment(assessment["id"], ASSESSOR),
            "ERR_ASSESSMENT_INVALID_STATE",
            409,
        )

        after = read_assessment(assessment["id"])
        assert_assessment(after)
        assert after["status"] == "CERTIFIED", after["status"]
        assert after["member_count"] == 1, (
            f"the refused second pass must not invoice the member twice, got "
            f"{after['member_count']}"
        )
        assert after["levied_amount_cents"] == 150_000, (
            f"the levy must not be double counted, got {after['levied_amount_cents']}"
        )

        invoices = list_member_assessments(assessment_id=assessment["id"], limit=100)
        assert len(invoices) == 1, f"one member, one invoice row, got {len(invoices)}"

    def test_certifying_over_a_member_with_no_written_premium_is_refused(self):
        """The eligible pool is the set of member insurer rows whose `account_status` is `ACTIVE`,
        whose `assessable_line` matches the assessment's `assessable_line`, whose `base_year` matches
        the assessment's `base_year`, and whose `direct_written_premium_cents` is strictly greater
        than 0.

        If the pool is empty, certification is refused with `ERR_PREMIUM_BASE_EMPTY`.

        Design: Corner/validations/certifying_with_no_positive_premium_base_is_refused
        """
        env = setup_triggered_insolvency(policy_overrides=dict(LIVE_TERM))
        register_member_insurer(
            naic_code="20001",
            insurer_name="Huron Standard Insurance",
            direct_written_premium_cents=0,
        )
        draft = draft_assessment(env["insolvency"]["id"], needed_amount_cents=150_000)
        assert draft["status"] == "DRAFT", draft["status"]

        validate_error(
            api_client.certify_assessment(draft["id"], ASSESSOR),
            "ERR_PREMIUM_BASE_EMPTY",
            422,
        )

        after = read_assessment(draft["id"])
        assert after["status"] == "DRAFT", (
            f"the refused certification leaves the levy in draft, got {after['status']}"
        )
        assert after["member_count"] == 0, after["member_count"]
        assert after["levied_amount_cents"] == 0, after["levied_amount_cents"]
        assert after["certified_at_utc"] is None
        assert list_member_assessments(assessment_id=draft["id"], limit=100) == [], (
            "a member with a zero premium base receives no invoice at all"
        )
        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["assessment_shortfall_cents"] == 0, (
            f"an uncertified levy books no shortfall, got "
            f"{insolvency['assessment_shortfall_cents']}"
        )


class TestMemberRegistrationAndCashCollection:
    """The uniqueness triple on registration, and the ceiling on a remittance."""

    def test_the_same_line_and_base_year_cannot_be_registered_twice(self):
        """The triple of `naic_code`, `assessable_line` and `base_year` must be unique across member
        insurer rows; a repeat registration is refused with `ERR_MEMBER_DUPLICATE_LINE`.

        Design: Corner/validations/registering_the_same_naic_line_and_base_year_twice_is_refused
        """
        first = register_member_insurer(**HURON_2025)
        assert first["base_year"] == 2025, first["base_year"]

        validate_error(
            api_client.create_member_insurer(
                member_insurer_payload(
                    **dict(HURON_2025, direct_written_premium_cents=11_000_000)
                ),
                ADMIN,
            ),
            "ERR_MEMBER_DUPLICATE_LINE",
            409,
        )

        other_year = get_success_data(
            api_client.create_member_insurer(
                member_insurer_payload(
                    **dict(
                        HURON_2025, base_year=2026, direct_written_premium_cents=11_000_000
                    )
                ),
                ADMIN,
            ),
            201,
        )
        assert_member_insurer(other_year)
        assert other_year["base_year"] == 2026, (
            "the same NAIC code and line for another base year is a distinct row, got "
            f"{other_year['base_year']}"
        )
        assert other_year["direct_written_premium_cents"] == 11_000_000

        unchanged = get_success_data(api_client.get_member_insurer(first["id"], ADMIN))
        assert unchanged["direct_written_premium_cents"] == 10_000_000, (
            "the refused repeat must not overwrite the registered premium base, got "
            f"{unchanged['direct_written_premium_cents']}"
        )

    def test_remitting_more_than_the_levy_is_refused(self):
        """When the sum would exceed `levied_amount_cents`, the payment is refused with
        `ERR_OVERPAYMENT`. Every payment recomputes the parent assessment's
        `collected_amount_cents` as the sum of `paid_amount_cents` across its invoices, and leaves
        `recoupment_status` untouched.

        Design: Corner/validations/paying_more_than_the_outstanding_levy_is_refused
        """
        env = setup_certified_assessment(
            member_specs=SMALL_BASE_MEMBER,
            needed_amount_cents=150_000,
            policy_overrides=dict(LIVE_TERM),
        )
        invoice = env["member_assessment"]
        assert invoice["levied_amount_cents"] == 150_000, invoice["levied_amount_cents"]
        assert invoice["paid_amount_cents"] == 0, invoice["paid_amount_cents"]

        validate_error(
            api_client.create_member_payment(
                invoice["id"], member_payment_payload(200_000, "WIRE-1"), env["agent"]
            ),
            "ERR_OVERPAYMENT",
            422,
        )

        after = read_member_assessment(invoice["id"])
        assert_member_assessment(after)
        assert after["billing_status"] == "INVOICED", (
            f"the refused remittance leaves the invoice unpaid, got {after['billing_status']}"
        )
        assert after["paid_amount_cents"] == 0, after["paid_amount_cents"]

        assessment = read_assessment(env["assessment"]["id"])
        assert assessment["status"] == "CERTIFIED", assessment["status"]
        assert assessment["collected_amount_cents"] == 0, (
            f"nothing was collected, got {assessment['collected_amount_cents']}"
        )


class TestRecoupmentDimensionGates:
    """One filing per levy, a cumulative rate ceiling, and no proceeds before a filing."""

    def test_a_second_surcharge_filing_on_one_levy_is_refused(self):
        """The `MemberInsurerAgent` files once per invoice, while `recoupment_status` is still
        `NOT_STARTED`, supplying `surcharge_rate_bps`, the `surcharge_base_cents` of written premium
        the surcharge applies to, and a `filing_ref`.

        The target member assessment invoice is in a declared origin state of the addressed
        dimension — `billing_status` for payments, `recoupment_status` for surcharge filings →
        `ERR_MEMBER_ASSESSMENT_INVALID_STATE` (HTTP 409), on
        `POST /member-assessments/{id}/payments` and `POST /member-assessments/{id}/surcharge-filings`.

        Design: Corner/validations/second_surcharge_filing_on_the_same_levy_is_refused
        """
        env = setup_member_assessment_with_surcharge(
            surcharge_rate_bps=25,
            surcharge_base_cents=60_000_000,
            member_specs=LARGE_BASE_MEMBER,
            needed_amount_cents=150_000,
            policy_overrides=dict(LIVE_TERM),
        )
        filed = env["member_assessment"]
        assert filed["recoupment_status"] == "SURCHARGE_FILED", filed["recoupment_status"]
        assert filed["projected_recoupment_cents"] == 150_000, (
            "60000000 at 25 bps is 150000, which is exactly the levy, got "
            f"{filed['projected_recoupment_cents']}"
        )

        validate_error(
            api_client.create_surcharge_filing(
                filed["id"], surcharge_filing_payload(10, 60_000_000, "SF-2"), env["agent"]
            ),
            "ERR_MEMBER_ASSESSMENT_INVALID_STATE",
            409,
        )

        after = read_member_assessment(filed["id"])
        assert after["recoupment_status"] == "SURCHARGE_FILED", after["recoupment_status"]
        assert after["surcharge_rate_bps"] == 25, (
            f"the refused filing must not overwrite the filed rate, got "
            f"{after['surcharge_rate_bps']}"
        )
        assert after["projected_recoupment_cents"] == 150_000, (
            after["projected_recoupment_cents"]
        )
        assert after["billing_status"] == "INVOICED", (
            f"a recoupment refusal touches no cash, got {after['billing_status']}"
        )

    def test_the_filed_rates_are_summed_across_the_members_levies(self):
        """There is a statutory aggregate: the sum of `surcharge_rate_bps` this member has already
        filed across its invoices whose `recoupment_status` is `SURCHARGE_FILED` or `RECOUPING`, plus
        the rate now requested, must stay at or below 300 basis points — three percent of written
        premium — and a filing that would push the total past that ceiling is refused with
        `ERR_SURCHARGE_AGGREGATE_EXCEEDED`.

        Each invoice starts with `paid_amount_cents`, `surcharge_rate_bps`, `surcharge_base_cents`,
        `projected_recoupment_cents` and `recouped_amount_cents` all at 0, with `billing_status`
        `INVOICED`, with `recoupment_status` `NOT_STARTED`, and with the next monotone `sequence`
        value within its parent assessment, which is the deterministic tie-break after `created_at`
        ascending in remainder-cent allocation.

        Design: Corner/validations/cumulative_surcharge_rate_above_three_hundred_bps_is_refused
        """
        env = setup_certified_assessment(
            member_specs=LARGE_BASE_MEMBER,
            needed_amount_cents=150_000,
            policy_overrides=dict(LIVE_TERM),
        )
        first_invoice = env["member_assessment"]

        second_levy = certify_assessment(
            draft_assessment(env["insolvency"]["id"], needed_amount_cents=150_000)["id"]
        )
        second_rows = list_member_assessments(assessment_id=second_levy["id"], limit=100)
        assert len(second_rows) == 1, f"the same member is levied again, got {len(second_rows)}"
        second_invoice = second_rows[0]
        assert second_invoice["recoupment_status"] == "NOT_STARTED"
        assert second_invoice["surcharge_rate_bps"] == 0, second_invoice["surcharge_rate_bps"]

        filed = file_surcharge(env, 200, 60_000_000, "SF-1", invoice=first_invoice)
        assert filed["surcharge_rate_bps"] == 200, filed["surcharge_rate_bps"]

        validate_error(
            api_client.create_surcharge_filing(
                second_invoice["id"],
                surcharge_filing_payload(150, 60_000_000, "SF-2"),
                env["agent"],
            ),
            "ERR_SURCHARGE_AGGREGATE_EXCEEDED",
            422,
        )

        refused = read_member_assessment(second_invoice["id"])
        assert refused["recoupment_status"] == "NOT_STARTED", (
            f"150 bps alone is legal, but 350 in aggregate is not, got "
            f"{refused['recoupment_status']}"
        )
        assert refused["surcharge_rate_bps"] == 0, refused["surcharge_rate_bps"]
        assert read_member_assessment(first_invoice["id"])["recoupment_status"] == (
            "SURCHARGE_FILED"
        )

        accepted = file_surcharge(env, 100, 60_000_000, "SF-3", invoice=second_invoice)
        assert accepted["recoupment_status"] == "SURCHARGE_FILED", (
            "a rate that brings the aggregate to exactly 300 bps is accepted, got "
            f"{accepted['recoupment_status']}"
        )
        assert accepted["surcharge_rate_bps"] == 100, accepted["surcharge_rate_bps"]

    def test_reporting_proceeds_before_any_filing_is_refused(self):
        """Remittance requires `recoupment_status` to be `SURCHARGE_FILED` or `RECOUPING`; a
        remittance while the dimension is still `NOT_STARTED` or already `RECOUPED` is refused with
        `ERR_RECOUPMENT_NOT_FILED`.

        Design: Corner/validations/remitting_surcharge_proceeds_before_filing_is_refused
        """
        env = setup_certified_assessment(
            member_specs=LARGE_BASE_MEMBER,
            needed_amount_cents=150_000,
            policy_overrides=dict(LIVE_TERM),
        )
        invoice = env["member_assessment"]
        assert invoice["recoupment_status"] == "NOT_STARTED", invoice["recoupment_status"]
        assert invoice["recouped_amount_cents"] == 0, invoice["recouped_amount_cents"]

        validate_error(
            api_client.create_recoupment_remittance(
                invoice["id"], recoupment_remittance_payload(50_000, "RR-1"), env["agent"]
            ),
            "ERR_RECOUPMENT_NOT_FILED",
            409,
        )

        after = read_member_assessment(invoice["id"])
        assert after["recoupment_status"] == "NOT_STARTED", after["recoupment_status"]
        assert after["recouped_amount_cents"] == 0, (
            f"proceeds cannot precede the filing, got {after['recouped_amount_cents']}"
        )
        assert after["billing_status"] == "INVOICED", after["billing_status"]
