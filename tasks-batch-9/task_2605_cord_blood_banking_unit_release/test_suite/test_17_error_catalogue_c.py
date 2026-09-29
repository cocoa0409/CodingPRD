"""State-family refusals: both ends of an excursion, a settled invoice, a dead hold and a lapsed window."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    acknowledge_excursion,
    build_bank_scenario,
    commission_tank,
    decline_reservation,
    expected_pre_cryo_dose,
    issue_invoice,
    latest_excursion,
    make_billing_admin_headers,
    make_facilities_engineer_headers,
    make_transplant_center_headers,
    open_storage_account,
    pay_invoice,
    place_reservation,
    post_temperature_reading,
    read_account,
    read_invoice,
    read_reservation,
    read_tank,
    read_unit,
    register_enrollment,
    resolve_excursion,
    set_clock,
    sign_consent,
    validate_error,
    validate_success,
)


def _alarmed_tank_with_one_open_excursion():
    """An empty tank driven to alarm at 01:00, so no quarantine cascade can interfere."""
    set_clock("2026-08-01T00:00:00Z")
    tank = commission_tank(tank_code="TANK-A", tank_class="STANDARD", capacity_slots=4)
    post_temperature_reading(tank["id"], reading_c=-140.0, reading_at="2026-08-01T01:00:00Z")
    return tank, latest_excursion(tank["id"])


class TestBothEndsOfTheExcursionStateCode:
    def test_resolving_an_excursion_that_was_never_acknowledged_is_refused(self):
        """Resolution has a declared inbound state set and `OPEN` is not in it.

        "Acknowledging an excursion that is neither `OPEN` nor `ESCALATED`, or resolving one that is
        neither `ACKNOWLEDGED` nor `ESCALATED`, is `ERR_INVALID_EXCURSION_STATE`."

        Design: Corner/errors/corner_excursion_resolve_before_acknowledge_and_acknowledge_after_resolve_are_both_refused
        """
        _, excursion = _alarmed_tank_with_one_open_excursion()
        assert excursion["status"] == "OPEN"

        set_clock("2026-08-01T01:10:00Z")
        response = api_client.resolve_excursion(
            excursion["id"],
            {"disposition": "NO_IMPACT", "peak_temperature_c": -140.0},
            make_facilities_engineer_headers("fe-001"),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_EXCURSION_STATE.value, 409)

    def test_the_legal_pair_of_transitions_runs_and_then_a_late_acknowledgement_is_refused(self):
        """A resolved row admits no acknowledgement, however well formed the request is.

        "It stamps `resolved_at` from the logical clock and computes `duration_minutes` as the whole
        minutes from `detected_at` to `resolved_at`, discarding any partial minute."

        Design: Corner/errors/corner_excursion_resolve_before_acknowledge_and_acknowledge_after_resolve_are_both_refused
        """
        tank, excursion = _alarmed_tank_with_one_open_excursion()

        acknowledged = acknowledge_excursion(excursion["id"], "2026-08-01T01:20:00Z")
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert acknowledged["acknowledged_at"].startswith("2026-08-01T01:20:00")

        resolved = resolve_excursion(excursion["id"], "NO_IMPACT", "2026-08-01T01:40:00Z")
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_at"].startswith("2026-08-01T01:40:00")
        assert resolved["duration_minutes"] == 40

        late = api_client.acknowledge_excursion(
            excursion["id"],
            {"acknowledgement_note": "second engineer arrives"},
            make_facilities_engineer_headers("fe-002"),
        )
        validate_error(late, ApiErrorId.ERR_INVALID_EXCURSION_STATE.value, 409)

        after = read_tank(tank["id"])
        assert after["status"] == "ONLINE"
        assert after["cumulative_excursion_minutes_30d"] == 40
        assert after["last_temperature_c"] == pytest.approx(-140.0, abs=0.01)


def _account_whose_only_invoice_is_settled_in_full():
    """An eighteen-year account with one fully paid invoice and a zero residual."""
    set_clock("2026-08-01T00:00:00Z")
    enrollment = register_enrollment(
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Avery Lin",
        collection_site_code="SITE-01",
    )
    sign_consent(enrollment["id"], consent_document_hash="hash-paid-v1")
    account = open_storage_account(
        enrollment["id"],
        billing_contact_email="avery@example.test",
        plan_term_years=18,
        prepaid_through_date="2044-08-01",
    )
    invoice = issue_invoice(
        account["id"],
        billing_period_start="2026-08-01",
        billing_period_end="2027-07-31",
        prorated_days=365,
    )
    assert invoice["amount_due_cents"] == 18225
    settled = pay_invoice(invoice["id"], 18225, payment_reference="WIRE-2026-FULL")
    assert settled["status"] == "PAID"
    return account, invoice


class TestPayingAnInvoiceThatIsAlreadySettled:
    def test_the_state_family_answers_before_the_fiscal_family(self):
        """Two rungs are violated at once and the earlier one must be the one reported.

        "Paying an invoice that is already `PAID`, `WRITTEN_OFF` or `VOID` is
        `ERR_INVALID_INVOICE_STATE`."

        "Checks are therefore evaluated in a single fixed order, and the **first** check that fails
        determines both the error identifier and the HTTP status; no later check may mask an earlier
        one, and no earlier check may be skipped because a later one would also fail."

        Design: Corner/errors/corner_payment_against_a_paid_invoice_is_a_state_error_not_a_balance_error
        """
        _, invoice = _account_whose_only_invoice_is_settled_in_full()

        response = api_client.pay_storage_invoice(
            invoice["id"],
            {"amount_cents": 1, "payment_reference": "WIRE-2026-EXTRA"},
            make_billing_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_INVOICE_STATE.value, 409)

    def test_the_refused_payment_never_reached_either_ledger(self):
        """The monotonic lifetime total and the invoice's paid figure both stand still.

        "An accepted payment adds `amount_cents` to the invoice's `amount_paid_cents` and to the
        account's `lifetime_paid_cents`, then triggers reconciliation of `balance_cents`."

        Design: Corner/errors/corner_payment_against_a_paid_invoice_is_a_state_error_not_a_balance_error
        """
        account, invoice = _account_whose_only_invoice_is_settled_in_full()
        api_client.pay_storage_invoice(
            invoice["id"],
            {"amount_cents": 1, "payment_reference": "WIRE-2026-EXTRA"},
            make_billing_admin_headers(),
        )

        after = read_invoice(invoice["id"])
        assert after["status"] == "PAID"
        assert after["amount_paid_cents"] == 18225
        assert after["amount_due_cents"] == 18225

        ledger = read_account(account["id"])
        assert ledger["balance_cents"] == 0
        assert ledger["lifetime_paid_cents"] == 18225


def _stored_private_unit_with_one_pending_hold():
    """A frozen private unit carrying one hold created on the receipt clock."""
    scenario = build_bank_scenario(
        stage="cryopreserved",
        tank_code="TANK-A",
        capacity_slots=4,
        program_type="PRIVATE_FAMILY",
        consent_document_hash="hash-hold-v1",
        kit_lot_code="LOT-2026-H",
        courier_tracking_code="TRK-0830",
        slot_code="A-01",
    )
    scenario["reservation"] = place_reservation(
        scenario["unit"]["id"],
        center_user_id="tc-001",
        requesting_center_name="Center One",
        patient_weight_kg=35.0,
        patient_hla_match_count=6,
        hold_from="2026-09-01T00:00:00Z",
        hold_until="2026-09-05T00:00:00Z",
    )
    return scenario


class TestDecliningAHoldTwice:
    def test_the_second_decline_is_refused_by_the_reservations_own_state_code(self):
        """Decline is the one hold action that touches no other row, so nothing can mask it.

        "Declining requires only that the acting `X-User-ID` equal `requesting_center_user_id` and
        that the hold still be `PENDING_CONFIRMATORY`; anything else is
        `ERR_INVALID_RESERVATION_STATE`."

        Design: Corner/errors/corner_declining_an_already_declined_reservation_is_refused
        """
        scenario = _stored_private_unit_with_one_pending_hold()
        assert scenario["reservation"]["status"] == "PENDING_CONFIRMATORY"

        declined = decline_reservation(
            scenario["reservation"]["id"],
            reason_code="ALTERNATIVE_UNIT_SELECTED",
            center_user_id="tc-001",
        )
        assert declined["status"] == "DECLINED"
        assert declined["cancellation_reason_code"] == "ALTERNATIVE_UNIT_SELECTED"

        response = api_client.decline_reservation(
            scenario["reservation"]["id"],
            {"reason_code": "ALTERNATIVE_UNIT_SELECTED"},
            make_transplant_center_headers("tc-001"),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_RESERVATION_STATE.value, 409)

    def test_the_refused_decline_is_invisible_on_both_the_hold_and_the_unit(self):
        """The unit's availability axis was never in play, before or after the refusal.

        "Declining is branch B, and it is the mirror image in scope: the centre supplies a
        `reason_code`, the hold moves `PENDING_CONFIRMATORY → DECLINED`, `cancellation_reason_code`
        is set to that `reason_code`, and **nothing else in the system changes**."

        Design: Corner/errors/corner_declining_an_already_declined_reservation_is_refused
        """
        scenario = _stored_private_unit_with_one_pending_hold()
        decline_reservation(
            scenario["reservation"]["id"],
            reason_code="ALTERNATIVE_UNIT_SELECTED",
            center_user_id="tc-001",
        )
        api_client.decline_reservation(
            scenario["reservation"]["id"],
            {"reason_code": "ALTERNATIVE_UNIT_SELECTED"},
            make_transplant_center_headers("tc-001"),
        )

        hold = read_reservation(scenario["reservation"]["id"])
        assert hold["status"] == "DECLINED"
        assert hold["intended_transplant_date"] is None
        assert hold["superseded_by_reservation_id"] is None

        unit = read_unit(scenario["unit"]["id"])
        assert unit["availability_status"] == "PRIVATE_STORED"
        assert unit["processing_status"] == "CRYOPRESERVED"


class TestConfirmingPastTheWindow:
    def test_one_hour_past_the_seventy_two_hour_deadline_is_refused(self):
        """The deadline is inclusive at 72 hours and this attempt sits an hour beyond it.

        "The centre supplies the `intended_transplant_date` and must act within 72 hours of the
        hold's `created_at`; the boundary is inclusive, so an attempt at exactly 72 hours succeeds
        and one past it is `ERR_CONFIRMATION_WINDOW_EXPIRED`."

        Design: Corner/errors/corner_confirming_one_hour_past_the_confirmation_window_is_refused
        """
        scenario = _stored_private_unit_with_one_pending_hold()
        assert scenario["reservation"]["created_at"].startswith("2026-08-11T00:00:00")

        set_clock("2026-08-14T01:00:00Z")
        response = api_client.confirm_reservation(
            scenario["reservation"]["id"],
            {"intended_transplant_date": "2026-09-03"},
            make_transplant_center_headers("tc-001"),
        )

        validate_error(response, ApiErrorId.ERR_CONFIRMATION_WINDOW_EXPIRED.value, 409)

    def test_the_window_is_enforced_at_confirm_time_rather_than_by_the_batch(self):
        """No nightly run has executed, so the hold is still pending rather than expired.

        "The third outward edge is involuntary: the nightly batch moves a hold
        `PENDING_CONFIRMATORY → EXPIRED` once the logical clock passes 72 hours after its
        `created_at`, recording a `cancellation_reason_code` of `CONFIRM_WINDOW_LAPSED`."

        Design: Corner/errors/corner_confirming_one_hour_past_the_confirmation_window_is_refused
        """
        scenario = _stored_private_unit_with_one_pending_hold()
        set_clock("2026-08-14T01:00:00Z")
        api_client.confirm_reservation(
            scenario["reservation"]["id"],
            {"intended_transplant_date": "2026-09-03"},
            make_transplant_center_headers("tc-001"),
        )

        hold = read_reservation(scenario["reservation"]["id"])
        assert hold["status"] == "PENDING_CONFIRMATORY"
        assert hold["cancellation_reason_code"] is None
        assert hold["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(2.86, abs=0.01)
        assert hold["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(
            expected_pre_cryo_dose(1000, 35.0), abs=0.01
        )

        unit = validate_success(
            api_client.get_unit(scenario["unit"]["id"], make_transplant_center_headers("tc-001"))
        )
        assert unit["availability_status"] == "PRIVATE_STORED"
