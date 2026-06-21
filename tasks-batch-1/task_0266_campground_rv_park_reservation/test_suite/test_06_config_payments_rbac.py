"""Park configuration and defaults, payment recording and ledger immutability,
config range / payment / season / clock validation errors, RBAC enforcement,
not-found handling, and list-endpoint envelopes.

Covers corner entities / errors / validations / rbac / endpoints claims.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    make_guest_headers,
    make_operator_headers,
    NON_EXISTENT_UUID,
    ApiErrorId,
    setup_base_scenario,
    setup_park,
    create_reservation,
    create_reservation_payload,
    create_payment_payload,
    pay_deposit,
    get_reservation,
)

OP = make_operator_headers()


# ===========================================================================
# Corner: entities / create_park_returns_201_with_defaults_applied
# ===========================================================================
def test_create_park_applies_config_defaults(api):
    """PRD §3.1: "`deposit_pct` is the fraction of the total charge collected as
    a deposit at confirmation time and defaults to 0.30; `tax_rate` is the
    lodging tax rate applied to the taxable base and defaults to 0.08; and
    `long_stay_nights_threshold` is the number of nights at or above which a stay
    is classified as long-term, defaulting to 28."
    PRD §3.1: "`quiet_hours_start` and `quiet_hours_end`, also local `HH:MM`
    strings (defaulting to `22:00` and `07:00`)."

    Design: Corner/entities/create_park_returns_201_with_defaults_applied
    """
    resp = api.create_park({"name": "Pinewood"}, OP)
    data = validate_success(resp, expected_status=201)
    assert data["deposit_pct"] == 0.30
    assert data["tax_rate"] == 0.08
    assert data["check_in_time"] == "15:00"
    assert data["quiet_hours_start"] == "22:00"
    assert data["long_stay_nights_threshold"] == 28
    assert data["version"] == 1


# ===========================================================================
# Corner: entities / create_park_missing_name_returns_invalid_request
# ===========================================================================
def test_create_park_without_name_rejected(api):
    """PRD §2.8: "Request well-formedness comes fourth — required fields present,
    enum values legal, dates parseable ... with any violation yielding
    `ERR_INVALID_REQUEST` (422)."
    PRD §3.1: "The top of the hierarchy is the **Park**, created by an operator
    with a `name`."

    Design: Corner/entities/create_park_missing_name_returns_invalid_request
    """
    resp = api.create_park({"timezone": "America/Denver"}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner: entities / get_reservation_nonexistent_returns_not_found
# ===========================================================================
def test_get_nonexistent_reservation_returns_not_found(api):
    """PRD §2.8: "The first identifier in the path that does not resolve to an
    existing resource causes immediate rejection with `ERR_NOT_FOUND` (HTTP
    404)"

    Design: Corner/entities/get_reservation_nonexistent_returns_not_found
    """
    resp = api.get_reservation(NON_EXISTENT_UUID, OP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Corner: entities / payment_is_immutable_no_version_field
# ===========================================================================
def test_payment_has_no_version_field(api):
    """PRD §2.4: "A payment is an append-only ledger entry and is therefore
    immutable after creation: it carries only an `id` and a `created_at` ... A
    payment has no `updated_at` and no `version` field at all."

    Design: Corner/entities/payment_is_immutable_no_version_field
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    resp = api.create_payment(
        res["id"], create_payment_payload("DEPOSIT", res["deposit_due_cents"]),
        make_guest_headers(guest["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["type"] == "DEPOSIT"
    assert "id" in data and "created_at" in data
    assert "version" not in data
    assert "updated_at" not in data


# ===========================================================================
# Corner: validations / season_overlap_rejected
# ===========================================================================
def test_overlapping_season_rejected(api):
    """PRD §3.2: "Seasons on a single park may never overlap: when a new season's
    closed date interval would intersect any existing season on that park, the
    creation is rejected with `ERR_SEASON_OVERLAP` (409)."

    Design: Corner/validations/season_overlap_rejected
    """
    park = setup_park(with_policy=False)
    validate_success(
        api.create_season(park["id"],
                          {"name": "PEAK", "start_date": "2026-08-01",
                           "end_date": "2026-08-31", "surcharge_pct": 12.5}, OP),
        expected_status=201)
    resp = api.create_season(
        park["id"],
        {"name": "SHOULDER", "start_date": "2026-08-15",
         "end_date": "2026-09-15", "surcharge_pct": 5}, OP)
    validate_error(resp, ApiErrorId.ERR_SEASON_OVERLAP.value)


# ===========================================================================
# Corner: validations / deposit_payment_wrong_amount_rejected
# ===========================================================================
def test_deposit_wrong_amount_rejected(api):
    """PRD §3.7: "A `DEPOSIT` payment whose `amount_cents` does not equal
    `deposit_due_cents` ... is rejected with `ERR_PAYMENT_AMOUNT_INVALID` (422)."

    Design: Corner/validations/deposit_payment_wrong_amount_rejected
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    resp = api.create_payment(
        res["id"], create_payment_payload("DEPOSIT", 1),
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID.value)


# ===========================================================================
# Corner: validations / site_rate_plan_type_mismatch_rejected
# ===========================================================================
def test_site_rate_plan_type_mismatch_rejected(api):
    """PRD §3.3: "the named rate plan's `site_type` must equal the site's own
    `site_type`, and a mismatch is rejected with `ERR_RATE_PLAN_TYPE_MISMATCH`
    (422)."

    Design: Corner/validations/site_rate_plan_type_mismatch_rejected
    """
    park = setup_park(with_policy=False)
    rate_plan = validate_success(
        api.create_rate_plan(park["id"],
                            {"site_type": "RV", "nightly_rate_cents": 5000,
                             "weekly_rate_cents": 30000, "monthly_rate_cents": 100000}, OP),
        expected_status=201)
    resp = api.create_site(
        park["id"],
        {"rate_plan_id": rate_plan["id"], "label": "C-1", "site_type": "CABIN",
         "hookup_level": "FULL", "max_length_of_stay_nights": 30}, OP)
    validate_error(resp, ApiErrorId.ERR_RATE_PLAN_TYPE_MISMATCH.value)


# ===========================================================================
# Corner: validations / create_reservation_checkout_before_checkin_rejected
# ===========================================================================
def test_reservation_checkout_not_after_checkin_rejected(api):
    """PRD §2.8: "Request well-formedness comes fourth — required fields present,
    enum values legal, dates parseable, `check_out_date` strictly later than
    `check_in_date`, and all amounts non-negative — with any violation yielding
    `ERR_INVALID_REQUEST` (422)."

    Design: Corner/validations/create_reservation_checkout_before_checkin_rejected
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    resp = api.create_reservation(
        site["id"],
        create_reservation_payload(guest["id"], "2026-08-11", "2026-08-01", site["version"]),
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner: errors / balance_payment_on_paid_in_full_returns_already_settled
# ===========================================================================
def test_balance_payment_on_paid_in_full_rejected(api):
    """PRD §3.7: "A payment attempted against a reservation that is already
    `PAID_IN_FULL` or `REFUNDED` is rejected with `ERR_PAYMENT_ALREADY_SETTLED`
    (409)."

    Design: Corner/errors/balance_payment_on_paid_in_full_returns_already_settled
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    pay_deposit(res, guest)  # 14580
    # Balance of 34020 brings amount_paid to total 48600 -> PAID_IN_FULL.
    validate_success(
        api.create_payment(res["id"], create_payment_payload("BALANCE", 34020),
                          make_guest_headers(guest["id"])),
        expected_status=201)
    resp = api.create_payment(
        res["id"], create_payment_payload("BALANCE", 100),
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_ALREADY_SETTLED.value)


# ===========================================================================
# Corner: errors / park_config_out_of_range_returns_validation_failed
# ===========================================================================
def test_park_deposit_pct_out_of_range_rejected(api):
    """PRD §3.1: "`deposit_pct` and `tax_rate` must each lie within the inclusive
    range from 0 to 1 ... A park or policy whose configuration falls outside
    these ranges is rejected with `ERR_VALIDATION_FAILED` (422)"

    Design: Corner/errors/park_config_out_of_range_returns_validation_failed
    """
    resp = api.create_park({"name": "Bad", "deposit_pct": 1.5}, OP)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)


# ===========================================================================
# Corner: errors / clock_set_invalid_timestamp_returns_clock_invalid
# ===========================================================================
def test_clock_set_unparseable_rejected(api):
    """PRD §3.10: "A `current_utc` that cannot be parsed is rejected with
    `ERR_CLOCK_INVALID` (422)."

    Design: Corner/errors/clock_set_invalid_timestamp_returns_clock_invalid
    """
    resp = api.set_clock("not-a-date", OP)
    validate_error(resp, ApiErrorId.ERR_CLOCK_INVALID.value)


# ===========================================================================
# Corner: rbac / guest_cannot_create_site
# ===========================================================================
def test_guest_cannot_create_site(api):
    """PRD §2.1: "An attempt to act outside one's permitted role, or a guest
    reaching for a reservation it does not own, is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/guest_cannot_create_site
    """
    park = setup_park(with_policy=False)
    rate_plan = validate_success(
        api.create_rate_plan(park["id"],
                            {"site_type": "RV", "nightly_rate_cents": 5000,
                             "weekly_rate_cents": 30000, "monthly_rate_cents": 100000}, OP),
        expected_status=201)
    guest = validate_success(
        api.create_guest({"email": "g1@x.com", "full_name": "Guest One"}, OP),
        expected_status=201)
    resp = api.create_site(
        park["id"],
        {"rate_plan_id": rate_plan["id"], "label": "X-1", "site_type": "RV",
         "hookup_level": "FULL", "max_length_of_stay_nights": 30},
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Corner: rbac / guest_cannot_act_on_other_guests_reservation
# ===========================================================================
def test_guest_cannot_confirm_other_guests_reservation(api):
    """PRD §2.1: "a guest acting on a reservation, an add-on, or a payment must
    own the underlying reservation — that is, the reservation's `guest_id` must
    equal `X-User-ID`. An attempt to act outside one's permitted role, or a guest
    reaching for a reservation it does not own, is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/guest_cannot_act_on_other_guests_reservation
    """
    park, rate_plan, site, guest_a = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30},
        guest_email="ga@x.com")
    guest_b = validate_success(
        api.create_guest({"email": "gb@x.com", "full_name": "Guest B"}, OP),
        expected_status=201)
    res = create_reservation(site, guest_a, "2026-08-01", "2026-08-11")
    pay_deposit(res, guest_a)
    resp = api.confirm_reservation(res["id"], make_guest_headers(guest_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    assert get_reservation(res["id"])["reservation_status"] == "REQUESTED"


# ===========================================================================
# Corner: rbac / missing_headers_returns_unauthenticated
# ===========================================================================
def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP
    headers: `X-User-ID`, which identifies the acting principal, and
    `X-User-Role`, which declares the capacity in which they are acting. If
    either header is missing or malformed, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api.get_park(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Corner: endpoints / list_site_reservations_returns_array_envelope
# ===========================================================================
def test_list_site_reservations_array_envelope(api):
    """PRD §2.3: "List responses surface the pagination state inside the
    envelope's `meta` object through the fields `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_site_reservations_returns_array_envelope
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    resp = api.list_site_reservations(site["id"], OP)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert any(r["id"] == res["id"] for r in data)


# ===========================================================================
# Corner: endpoints / list_guest_reservations_reverse_reachability
# ===========================================================================
def test_list_guest_reservations_finds_by_guest_id(api):
    """PRD §3.5: "A guest can be fetched, and its own reservations listed
    (optionally filtered by `reservation_status`)."

    Design: Corner/endpoints/list_guest_reservations_reverse_reachability
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    resp = api.list_guest_reservations(guest["id"], make_guest_headers(guest["id"]))
    data, meta = validate_paginated(resp)
    matched = [r for r in data if r["id"] == res["id"]]
    assert len(matched) == 1
    assert matched[0]["guest_id"] == guest["id"]
