"""
Tuition-invoice pricing: the dual-basis waterfall and the variance branch.

Every figure asserted here is derived from the pinned rate schedule (day 32000,
residential 51500, service hour 11000 cents unless a test overrides it), the
twenty-eight-day cycle the record covers, and the rounding order the requirements
fix for line totals, the volume credit and the administrative fee.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ATTENDANCE_NOT_VERIFIED,
    ERR_INVALID_REQUEST,
    ERR_STALE_PLACEMENT_VERSION,
)
from test_helpers.assertions import assert_invoice_lines
from test_helpers.fixtures import (
    ATTENDANCE_FILING_INSTANT,
    FULL_MONTH_PERIOD,
    add_authorized_addendum,
    build_active_day_placement,
    build_simple_billing_cycle,
    build_two_addenda_world,
    create_invoice,
    file_attendance,
    list_rows,
    placement_version,
    read_account,
    read_addendum,
    read_attendance,
    read_invoice,
    read_placement,
    set_clock,
    verify_attendance,
    verify_invoice,
)
from test_helpers.test_users import COORDINATOR_HEADERS, FISCAL_OFFICER_HEADERS

# ─── The two-addendum cycle ───────────────────────────────────────────────────
# 20 days enrolled, 16 attended, 4 unexcused, 7.5 speech hours and 5.5 OT hours.
#
#   enrolment basis    20 billable days x 32000       = 640000 tuition
#   attendance basis   (16 + min(4, 3)) x 32000       = 608000 tuition
#   speech line        7.5 x 11000 x 1.075 =  88687.5 ->  88688
#   OT line            5.5 x 11000 x 1.075 =  65037.5 ->  65038
#   service total      88688 + 65038                  = 153726
ENROLMENT_TUITION_CENTS = 640000
ATTENDANCE_TUITION_CENTS = 608000
SPEECH_LINE_CENTS = 88688
OT_LINE_CENTS = 65038
SERVICE_TOTAL_CENTS = 153726
SERVICE_TOTAL_IF_ROUNDED_ONCE_CENTS = 153725

ENROLMENT_GROSS_CENTS = 793726
ENROLMENT_CREDIT_CENTS = 11906
ENROLMENT_FEE_CENTS = 17591
ENROLMENT_NET_CENTS = 799411

ATTENDANCE_GROSS_CENTS = 761726
ATTENDANCE_CREDIT_CENTS = 11426
ATTENDANCE_FEE_CENTS = 16882
ATTENDANCE_NET_CENTS = 767182

BASIS_GAP_CENTS = 32229

# ─── The tier-boundary cycle (day rate 50000, 20/20/0, no addenda) ────────────
TIER_RATE_OVERRIDES = {"day_rate_cents": 50000}
TIER_GROSS_CENTS = 1000000
TIER_CREDIT_CENTS = 30000
TIER_SUBTOTAL_CENTS = 970000
TIER_FEE_CENTS = 21825
TIER_NET_CENTS = 991825
CREDIT_IF_KEYED_ON_SUBTOTAL_CENTS = 14550
NET_IF_KEYED_ON_SUBTOTAL_CENTS = 1007623

# ─── The plain cycle (20/20/0, no addenda, day rate 32000) ────────────────────
PLAIN_NET_CENTS = 654400

# ─── Variance boundary submissions over a verified 767182 ─────────────────────
SUBMITTED_ROUNDS_DOWN_CENTS = 782526
SUBMITTED_LAST_PASSING_CENTS = 782563
SUBMITTED_FIRST_FAILING_CENTS = 782564

# Three consecutive twenty-eight-day cycles inside the placement window.
CYCLE_ONE = {"period_start": "2026-09-01", "period_end": "2026-09-28"}
CYCLE_TWO = {"period_start": "2026-09-29", "period_end": "2026-10-26"}
CYCLE_THREE = {"period_start": "2026-10-27", "period_end": "2026-11-23"}
CYCLE_ONE_FILED_AT = "2026-09-29T09:00:00Z"
CYCLE_TWO_FILED_AT = "2026-10-27T09:00:00Z"
CYCLE_THREE_FILED_AT = "2026-11-24T09:00:00Z"


def _price_two_addenda_cycle(
    api,
    world,
    *,
    submitted_amount_cents,
    basis,
    period=None,
    filing_instant=ATTENDANCE_FILING_INSTANT,
):
    """
    File one 20/16/4 cycle carrying 7.5 speech hours and 5.5 OT hours, verify the
    record, invoice it at the given claim and price it under the given basis.
    """
    period = period or FULL_MONTH_PERIOD
    placement_id = world["placement"]["id"]
    set_clock(api, filing_instant)
    record = file_attendance(
        api,
        world,
        placement_id,
        days_enrolled=20,
        days_attended=16,
        days_absent_unexcused=4,
        residential_nights=0,
        service_delivery_lines=[
            f.service_line(world["speech"]["id"], 7.5),
            f.service_line(world["ot"]["id"], 5.5),
        ],
        **period,
    )
    verify_attendance(api, record["id"])
    invoice = create_invoice(
        api,
        world,
        placement_id,
        record["id"],
        submitted_amount_cents,
        billing_period_start=period["period_start"],
        billing_period_end=period["period_end"],
        transport_days_billed=0,
    )
    return record, verify_invoice(api, invoice["id"], basis)


class TestInvoiceBasisFork:
    """The two bases disagree only on the billable-day count, and both are stored."""

    def test_enrolment_basis_bills_every_held_seat_day(self, api):
        """
        Twenty enrolled days price the tuition line, the absences are irrelevant,
        and the enrolment figure becomes the verified amount.

        PRD: "Under the `ENROLLMENT` basis the billable-day count is simply `days_enrolled` — every held-seat day is billed regardless of whether the student showed up, which is the reserved-seat contract basis the school bills on while the cycle is open."

        Design: Difficulty/dual_variant_calc/invoice_enrollment_basis_versus_attendance_basis
        """
        world = build_two_addenda_world(api)
        _, invoice = _price_two_addenda_cycle(
            api,
            world,
            submitted_amount_cents=ENROLMENT_NET_CENTS,
            basis="ENROLLMENT",
        )

        assert_invoice_lines(
            invoice,
            ENROLMENT_TUITION_CENTS,
            0,
            SERVICE_TOTAL_CENTS,
            0,
            ENROLMENT_GROSS_CENTS,
        )
        assert invoice["volume_credit_cents"] == ENROLMENT_CREDIT_CENTS
        assert invoice["admin_fee_cents"] == ENROLMENT_FEE_CENTS
        assert invoice["provisional_amount_cents"] == ENROLMENT_NET_CENTS
        assert invoice["final_amount_cents"] == ATTENDANCE_NET_CENTS
        assert invoice["verified_amount_cents"] == ENROLMENT_NET_CENTS
        assert invoice["verification_basis"] == "ENROLLMENT"
        assert invoice["variance_pct"] == pytest.approx(0.0)
        assert invoice["verification_status"] == "VERIFIED"
        assert invoice["payment_status"] == "UNPAID"

    def test_attendance_basis_abates_the_fourth_unexcused_day(self, api):
        """
        Sixteen attended days plus the three-day tolerance price nineteen days,
        and the same row still carries the enrolment figure alongside.

        PRD: "Under the `ATTENDANCE` basis it is `days_attended` plus the lesser of `days_absent_unexcused` and three, meaning the first three unexcused absence days remain billable as a tolerance and every unexcused absence beyond the third is abated."

        Design: Difficulty/dual_variant_calc/invoice_enrollment_basis_versus_attendance_basis
        """
        world = build_two_addenda_world(api)
        _, invoice = _price_two_addenda_cycle(
            api,
            world,
            submitted_amount_cents=ATTENDANCE_NET_CENTS,
            basis="ATTENDANCE",
        )

        assert_invoice_lines(
            invoice,
            ATTENDANCE_TUITION_CENTS,
            0,
            SERVICE_TOTAL_CENTS,
            0,
            ATTENDANCE_GROSS_CENTS,
        )
        assert invoice["volume_credit_cents"] == ATTENDANCE_CREDIT_CENTS
        assert invoice["admin_fee_cents"] == ATTENDANCE_FEE_CENTS
        assert invoice["provisional_amount_cents"] == ENROLMENT_NET_CENTS
        assert invoice["final_amount_cents"] == ATTENDANCE_NET_CENTS
        assert (
            invoice["provisional_amount_cents"] - invoice["final_amount_cents"]
            == BASIS_GAP_CENTS
        )
        assert invoice["verified_amount_cents"] == ATTENDANCE_NET_CENTS
        assert invoice["verification_basis"] == "ATTENDANCE"
        assert invoice["variance_pct"] == pytest.approx(0.0)
        assert invoice["verification_status"] == "VERIFIED"
        assert invoice["payment_status"] == "UNPAID"


class TestServiceLineRoundingOrder:
    """Two lines that both land on an exact half cent expose the rounding order."""

    def test_each_service_line_is_rounded_before_the_lines_are_added(self, api):
        """
        88687.5 and 65037.5 round to 88688 and 65038 for a total of 153726; summing
        the raw products and rounding once would have produced 153725.

        PRD: "`service_lines_total_cents` is the sum of those already-rounded per-entry lines, never a single rounding of the combined product."

        Design: Difficulty/combinatorial_formula/invoice_service_lines_rounded_per_line_before_summation
        """
        world = build_two_addenda_world(api)
        _, invoice = _price_two_addenda_cycle(
            api,
            world,
            submitted_amount_cents=ATTENDANCE_NET_CENTS,
            basis="ATTENDANCE",
        )

        assert invoice["service_lines_total_cents"] == SERVICE_TOTAL_CENTS
        assert invoice["service_lines_total_cents"] != SERVICE_TOTAL_IF_ROUNDED_ONCE_CENTS
        assert SPEECH_LINE_CENTS + OT_LINE_CENTS == SERVICE_TOTAL_CENTS
        assert invoice["gross_billable_cents"] == ATTENDANCE_GROSS_CENTS
        assert invoice["verified_amount_cents"] == ATTENDANCE_NET_CENTS
        assert invoice["variance_pct"] == pytest.approx(0.0)
        assert invoice["verification_status"] == "VERIFIED"

        assert read_addendum(api, world["speech"]["id"])["delivered_hours_ytd"] == (
            pytest.approx(7.5)
        )
        assert read_addendum(api, world["ot"]["id"])["delivered_hours_ytd"] == (
            pytest.approx(5.5)
        )

    def test_the_per_line_total_is_the_same_under_the_enrolment_basis(self, api):
        """
        The rounding order belongs to the service lines, not to the day count, so
        the enrolment run reports the identical 153726.

        PRD: "**Second**, four billing lines are computed, and — per §2.5 — each is rounded to whole cents *before* any of them are added together."

        Design: Difficulty/combinatorial_formula/invoice_service_lines_rounded_per_line_before_summation
        """
        world = build_two_addenda_world(api)
        _, invoice = _price_two_addenda_cycle(
            api,
            world,
            submitted_amount_cents=ENROLMENT_NET_CENTS,
            basis="ENROLLMENT",
        )

        assert invoice["service_lines_total_cents"] == SERVICE_TOTAL_CENTS
        assert invoice["service_lines_total_cents"] != SERVICE_TOTAL_IF_ROUNDED_ONCE_CENTS
        assert (
            invoice["gross_billable_cents"] - invoice["tuition_line_cents"]
            == SERVICE_TOTAL_CENTS
        )
        assert invoice["tuition_line_cents"] == ENROLMENT_TUITION_CENTS
        assert invoice["verified_amount_cents"] == ENROLMENT_NET_CENTS
        assert invoice["verification_status"] == "VERIFIED"


class TestVolumeCreditTierKeying:
    """A gross sitting exactly on the top floor whose subtotal falls below it."""

    def test_the_credit_rate_is_keyed_on_the_gross_and_not_on_the_subtotal(self, api):
        """
        A gross of exactly 1 000 000 earns the three-percent credit even though the
        post-credit subtotal of 970 000 is below that floor.

        PRD: "The tier is keyed on `gross_billable_cents` **only**, never on the subtotal and never on the net."

        Design: Difficulty/combinatorial_formula/net_payable_volume_tier_keyed_on_gross_not_subtotal
        """
        world = build_simple_billing_cycle(api, rate_overrides=TIER_RATE_OVERRIDES)
        invoice = create_invoice(
            api,
            world,
            world["placement"]["id"],
            world["record"]["id"],
            TIER_NET_CENTS,
            **{
                "billing_period_start": FULL_MONTH_PERIOD["period_start"],
                "billing_period_end": FULL_MONTH_PERIOD["period_end"],
            },
        )
        priced = verify_invoice(api, invoice["id"], "ENROLLMENT")

        assert priced["gross_billable_cents"] == TIER_GROSS_CENTS
        assert priced["volume_credit_cents"] == TIER_CREDIT_CENTS
        assert priced["volume_credit_cents"] != CREDIT_IF_KEYED_ON_SUBTOTAL_CENTS
        assert priced["admin_fee_cents"] == TIER_FEE_CENTS
        assert priced["verified_amount_cents"] == TIER_NET_CENTS
        assert priced["verified_amount_cents"] != NET_IF_KEYED_ON_SUBTOTAL_CENTS
        assert priced["verification_status"] == "VERIFIED"

    def test_both_variants_land_on_the_same_net_when_the_day_counts_agree(self, api):
        """
        With no unexcused absences the two bases share a gross, so both stored
        amounts equal 991825 and the fee is the subtotal's 2.25 percent.

        PRD: "The credit rate is 3% when the gross is at least 1 000 000 cents (ten thousand dollars), 1.5% when the gross is at least 700 000 cents (seven thousand dollars) but below the higher floor, and 0% otherwise; both floors are inclusive."

        Design: Difficulty/combinatorial_formula/net_payable_volume_tier_keyed_on_gross_not_subtotal
        """
        world = build_simple_billing_cycle(api, rate_overrides=TIER_RATE_OVERRIDES)
        invoice = create_invoice(
            api,
            world,
            world["placement"]["id"],
            world["record"]["id"],
            TIER_NET_CENTS,
            **{
                "billing_period_start": FULL_MONTH_PERIOD["period_start"],
                "billing_period_end": FULL_MONTH_PERIOD["period_end"],
            },
        )
        priced = verify_invoice(api, invoice["id"], "ENROLLMENT")

        assert priced["provisional_amount_cents"] == TIER_NET_CENTS
        assert priced["final_amount_cents"] == TIER_NET_CENTS
        assert (
            priced["gross_billable_cents"] - priced["volume_credit_cents"]
            == TIER_SUBTOTAL_CENTS
        )
        assert priced["admin_fee_cents"] == TIER_FEE_CENTS
        assert (
            TIER_SUBTOTAL_CENTS + priced["admin_fee_cents"]
            == priced["verified_amount_cents"]
        )
        assert priced["variance_pct"] == pytest.approx(0.0)


class TestVarianceTolerance:
    """The variance is rounded to four decimals first and then compared strictly."""

    def test_a_raw_ratio_above_two_percent_that_rounds_down_still_verifies(self, api):
        """
        782526 over a verified 767182 is a raw ratio of 0.0200004692, which rounds
        to 0.0200 and therefore is not greater than the tolerance.

        PRD: "`variance_pct` is the absolute difference between `submitted_amount_cents` and `verified_amount_cents`, divided by `verified_amount_cents`, rounded half up to four decimal places."

        Design: Difficulty/boundary_precision_check/variance_tolerance_exclusive_at_0_0200_and_disputes_at_0_0201
        """
        world = build_two_addenda_world(api)
        _, invoice = _price_two_addenda_cycle(
            api,
            world,
            submitted_amount_cents=SUBMITTED_ROUNDS_DOWN_CENTS,
            basis="ATTENDANCE",
            period=CYCLE_ONE,
            filing_instant=CYCLE_ONE_FILED_AT,
        )

        assert invoice["verified_amount_cents"] == ATTENDANCE_NET_CENTS
        assert invoice["gross_billable_cents"] == ATTENDANCE_GROSS_CENTS
        assert invoice["volume_credit_cents"] == ATTENDANCE_CREDIT_CENTS
        assert invoice["admin_fee_cents"] == ATTENDANCE_FEE_CENTS
        assert invoice["variance_pct"] == pytest.approx(0.0200, abs=0.00005)
        assert invoice["verification_status"] == "VERIFIED"
        assert invoice["payment_status"] == "UNPAID"

    def test_one_cent_more_rounds_to_0_0201_and_disputes(self, api):
        """
        782563 is the last submission that still rounds to 0.0200 and verifies;
        782564 is the first that rounds to 0.0201 and disputes.

        PRD: "If `variance_pct` is greater than 0.02 — that is, if the school's claim is off by more than two percent of the district's own figure — the invoice auto-branches `SUBMITTED → DISPUTED`; otherwise it goes `SUBMITTED → VERIFIED`, which is terminal for the verification dimension."

        Design: Difficulty/boundary_precision_check/variance_tolerance_exclusive_at_0_0200_and_disputes_at_0_0201
        """
        world = build_two_addenda_world(api)
        _, last_passing = _price_two_addenda_cycle(
            api,
            world,
            submitted_amount_cents=SUBMITTED_LAST_PASSING_CENTS,
            basis="ATTENDANCE",
            period=CYCLE_TWO,
            filing_instant=CYCLE_TWO_FILED_AT,
        )
        _, first_failing = _price_two_addenda_cycle(
            api,
            world,
            submitted_amount_cents=SUBMITTED_FIRST_FAILING_CENTS,
            basis="ATTENDANCE",
            period=CYCLE_THREE,
            filing_instant=CYCLE_THREE_FILED_AT,
        )

        assert (
            SUBMITTED_FIRST_FAILING_CENTS - SUBMITTED_LAST_PASSING_CENTS == 1
        )
        assert last_passing["variance_pct"] == pytest.approx(0.0200, abs=0.00005)
        assert last_passing["verification_status"] == "VERIFIED"

        assert first_failing["verified_amount_cents"] == ATTENDANCE_NET_CENTS
        assert first_failing["variance_pct"] == pytest.approx(0.0201, abs=0.00005)
        assert first_failing["verification_status"] == "DISPUTED"
        assert first_failing["payment_status"] == "UNPAID"
        assert first_failing["resubmission_round"] == 0


def _invoice_over_an_unverified_record(api):
    """
    An ACTIVE placement, a 20/20/0 record deliberately left `SUBMITTED`, and an
    invoice raised against it for the plain 654400-cent net.
    """
    world = build_active_day_placement(api)
    placement_id = world["placement"]["id"]
    set_clock(api, CYCLE_ONE_FILED_AT)
    record = file_attendance(
        api,
        world,
        placement_id,
        days_enrolled=20,
        days_attended=20,
        days_absent_unexcused=0,
        residential_nights=0,
        service_delivery_lines=[],
        **CYCLE_ONE,
    )
    assert record["status"] == "SUBMITTED"
    created = validate_success(
        api.create_tuition_invoice(
            f.tuition_invoice_payload(
                placement_id,
                record["id"],
                PLAIN_NET_CENTS,
                placement_version(api, placement_id),
                billing_period_start=CYCLE_ONE["period_start"],
                billing_period_end=CYCLE_ONE["period_end"],
                transport_days_billed=0,
            ),
            world["school_headers"],
        ),
        201,
    )
    return world, record, created


class TestInvoiceVerificationGate:
    """Pricing waits on the linked attendance record, not on the invoice itself."""

    def test_pricing_is_refused_while_the_linked_record_is_only_submitted(self, api):
        """
        The invoice may be raised against a `SUBMITTED` record, but verifying it
        is refused and leaves every computed figure at zero.

        PRD: "The linked attendance record must already be `VERIFIED`; verification attempted while it is `SUBMITTED` or `DISPUTED` is refused with `ERR_ATTENDANCE_NOT_VERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/invoice_verification_gated_on_attendance_record_verification
        """
        world, record, created = _invoice_over_an_unverified_record(api)

        response = api.verify_tuition_invoice(
            created["id"], f.verify_invoice_payload("ENROLLMENT"), COORDINATOR_HEADERS
        )
        validate_error(response, ERR_ATTENDANCE_NOT_VERIFIED, 409)

        stale = read_invoice(api, created["id"])
        assert stale["verification_status"] == "SUBMITTED"
        assert stale["verified_amount_cents"] == 0
        assert stale["variance_pct"] == pytest.approx(0.0)
        assert stale["verification_basis"] is None
        assert stale["verified_by_user_id"] is None
        assert read_attendance(api, record["id"])["status"] == "SUBMITTED"

    def test_the_same_call_succeeds_once_the_record_is_verified(self, api):
        """
        Accepting the attendance record opens the gate, and pricing then verifies
        the invoice without moving any money.

        PRD: "The linked attendance record must already be `VERIFIED`; verification attempted while it is `SUBMITTED` or `DISPUTED` is refused with `ERR_ATTENDANCE_NOT_VERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/invoice_verification_gated_on_attendance_record_verification
        """
        world, record, created = _invoice_over_an_unverified_record(api)
        validate_error(
            api.verify_tuition_invoice(
                created["id"], f.verify_invoice_payload("ENROLLMENT"), COORDINATOR_HEADERS
            ),
            ERR_ATTENDANCE_NOT_VERIFIED,
            409,
        )

        accepted = verify_attendance(api, record["id"])
        assert accepted["status"] == "VERIFIED"
        assert accepted["verified_by_user_id"] == "u-coord-1"

        priced = validate_success(
            api.verify_tuition_invoice(
                created["id"],
                f.verify_invoice_payload("ENROLLMENT"),
                COORDINATOR_HEADERS,
            )
        )
        assert priced["verification_status"] == "VERIFIED"
        assert priced["verified_amount_cents"] == PLAIN_NET_CENTS
        assert priced["variance_pct"] == pytest.approx(0.0)
        assert priced["payment_status"] == "UNPAID"
        assert read_account(api, world["account"]["id"])["disbursed_cents"] == 0


class TestInvoiceCreateGuards:
    """The optimistic-concurrency token is required, and it must be current."""

    def test_omitting_the_expected_placement_version_is_a_shape_failure(self, api):
        """
        A missing concurrency token is a malformed request, not a stale view.

        PRD: "On every creating or modifying request: required fields present, enum values inside their declared sets, integers non-negative where required, dates well-formed ISO 8601 calendar dates or date-times, monetary fields supplied as integer cents rather than decimal strings, and no unknown field names."

        Design: Corner/validations/invoice_create_without_expected_placement_version_rejected
        """
        world = build_simple_billing_cycle(api)
        placement_id = world["placement"]["id"]
        payload = f.tuition_invoice_payload(
            placement_id,
            world["record"]["id"],
            PLAIN_NET_CENTS,
            placement_version(api, placement_id),
            transport_days_billed=0,
        )
        payload.pop("expected_placement_version")

        response = api.create_tuition_invoice(payload, world["school_headers"])
        validate_error(response, ERR_INVALID_REQUEST, 400)

        _, meta = list_rows(
            api.list_tuition_invoices(
                COORDINATOR_HEADERS, {"placement_id": placement_id}
            )
        )
        assert meta["total_count"] == 0

    def test_a_version_stale_by_one_addendum_is_refused_then_retried(self, api):
        """
        Authorizing an addendum advances the placement, so the token captured
        before it is stale; the refreshed token makes the identical create legal.

        PRD: "`expected_placement_version` must equal the placement's current `version` on invoice creation; `expected_school_version` must equal the school's current `version` on rate-schedule creation."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_placement_version_on_invoice_create_returns_412
        """
        world = build_simple_billing_cycle(api)
        placement_id = world["placement"]["id"]
        captured_version = placement_version(api, placement_id)
        assert captured_version == 3

        add_authorized_addendum(
            api,
            placement_id,
            service_type="SPEECH",
            authorized_hours_per_week=2.0,
            contract_weeks=36,
            medicaid_billable=False,
        )

        stale_payload = f.tuition_invoice_payload(
            placement_id,
            world["record"]["id"],
            PLAIN_NET_CENTS,
            captured_version,
            transport_days_billed=0,
        )
        validate_error(
            api.create_tuition_invoice(stale_payload, world["school_headers"]),
            ERR_STALE_PLACEMENT_VERSION,
            412,
        )

        current = read_placement(api, placement_id)
        assert current["version"] == 4
        assert current["addendum_encumbrance_cents"] == 792000

        fresh_payload = f.tuition_invoice_payload(
            placement_id,
            world["record"]["id"],
            PLAIN_NET_CENTS,
            current["version"],
            transport_days_billed=0,
        )
        created = validate_success(
            api.create_tuition_invoice(fresh_payload, world["school_headers"]), 201
        )
        assert created["verification_status"] == "SUBMITTED"

        _, meta = list_rows(
            api.list_tuition_invoices(
                FISCAL_OFFICER_HEADERS, {"placement_id": placement_id}
            )
        )
        assert meta["total_count"] == 1
