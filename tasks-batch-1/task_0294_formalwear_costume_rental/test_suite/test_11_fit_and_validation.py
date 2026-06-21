"""Corner: window-coherence validation, fit-check verdicts, and the
NEEDS_ALTERATION pickup gate."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, create_catalog, create_unit, create_customer, create_reservation,
    confirm, create_measurement_profile,
)
from test_helpers import api_client
from test_helpers import TEST_USERS
from test_helpers.factories import (
    create_reservation_payload, create_fit_check_payload, create_alteration_payload,
)

CLERK = TEST_USERS["clerk_headers"]

CAT = {
    "daily_rate_cents": 5000, "deposit_cents": 20000, "replacement_value_cents": 80000,
    "waiver_daily_rate_cents": 1200, "cleaning_buffer_days": 2, "late_fee_daily_rate_cents": 2000,
}


def test_reservation_window_incoherent_returns_invalid_window(api):
    """PRD §3.3: "the `pickup_window_start_iso` must be on or before the `return_window_end_iso`, the pickup window must end on or before the `event_date_iso`, and the `event_date_iso` must lie strictly in the future relative to the current clock. Any violation of these temporal rules is rejected with `ERR_INVALID_WINDOW`."

    Design: Corner/validations/reservation_window_incoherent_returns_invalid_window
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux S"})
    customer = create_customer()
    # pickup_start (09-05) is AFTER return_end (09-01).
    res = api_client.create_reservation(
        create_reservation_payload(customer["id"], catalog["id"], requested_size_code="M",
                                   event_date_iso="2026-09-06T00:00:00Z",
                                   pickup_window_start_iso="2026-09-05T09:00:00Z",
                                   return_window_end_iso="2026-09-01T09:00:00Z"),
        CLERK)
    validate_error(res, ApiErrorId.ERR_INVALID_WINDOW)


def test_pickup_fit_fail_returns_fit_not_cleared(api):
    """PRD §3.5: "A difference of 2 or more yields `FAIL` — the garment cannot be made to fit."
    PRD §3.6: "there must exist a `FitCheck` on the reservation with a `verdict` of `PASS`, or one with `verdict` `NEEDS_ALTERATION` accompanied by at least one `COMPLETED` alteration on the reservation; a `FAIL` verdict never clears pickup. A reservation that is not fit-cleared is rejected with `ERR_FIT_NOT_CLEARED`."

    Design: Corner/validations/pickup_fit_fail_returns_fit_not_cleared
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux R"})
    create_unit(catalog["id"], "XS")
    customer = create_customer()
    # chest 110 -> recommended L (ordinal 3); requested XS (ordinal 0); delta 3 -> FAIL.
    mp = create_measurement_profile(customer["id"], chest_cm=110, waist_cm=96, inseam_cm=84)
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="XS")
    validate_success(confirm(resv["id"]), 200)
    fit = validate_success(api_client.create_fit_check(
        create_fit_check_payload(resv["id"], mp["id"]), CLERK), 201)
    assert fit["verdict"] == "FAIL"

    res = api_client.pickup_reservation(resv["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_FIT_NOT_CLEARED)
    after = validate_success(api_client.get_reservation(resv["id"], CLERK), 200)
    assert after["status"] == "CONFIRMED"


def test_fit_needs_alteration_cleared_by_completed_alteration(api):
    """PRD §3.5: "A difference of exactly 1 yields `NEEDS_ALTERATION` — an adjacent size that tailoring can close."
    PRD §3.6: "or one with `verdict` `NEEDS_ALTERATION` accompanied by at least one `COMPLETED` alteration on the reservation".

    Design: Corner/validations/fit_needs_alteration_cleared_by_completed_alteration
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux Q2"})
    create_unit(catalog["id"], "M")
    customer = create_customer()
    # chest 110 -> recommended L (ordinal 3); requested M (ordinal 2); delta 1 -> NEEDS_ALTERATION.
    mp = create_measurement_profile(customer["id"], chest_cm=110, waist_cm=92, inseam_cm=84)
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M")
    validate_success(confirm(resv["id"]), 200)
    fit = validate_success(api_client.create_fit_check(
        create_fit_check_payload(resv["id"], mp["id"]), CLERK), 201)
    assert fit["verdict"] == "NEEDS_ALTERATION"

    # Complete a zero-fee alteration so balance stays 0 and the gate clears.
    alt = validate_success(api_client.create_alteration(
        create_alteration_payload(resv["id"], kind="LET_OUT", fee_cents=0), CLERK), 201)
    validate_success(api_client.complete_alteration(alt["id"], CLERK), 200)

    picked = validate_success(api_client.pickup_reservation(resv["id"], CLERK), 200)
    assert picked["status"] == "PICKED_UP", "cleared by the COMPLETED alteration"
