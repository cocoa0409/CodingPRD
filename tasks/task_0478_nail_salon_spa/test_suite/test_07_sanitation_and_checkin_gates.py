"""Sanitation discipline (PASS thresholds, freshness derivation) and the two
cross-entity check-in gates: station sterility and technician license validity."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    TEST_USERS, make_technician_headers,
    create_sanitation_log_payload,
    make_station, make_menu_item, make_technician, make_client,
    book_appointment, confirm, record_pass_sanitation, set_clock,
)

MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Corner: sterilization PASS thresholds
# ---------------------------------------------------------------------------
def test_sanitation_pass_below_temp_rejected(api):
    """PRD §3.2: "A log claiming `PASS` is only honored if its `cycle_temp_c` is at
    least 121.0 and its `hold_minutes` is at least 30; a `PASS` claim that fails
    either of these thresholds is physically inconsistent and is rejected with
    `ERR_STERILIZATION_INVALID`."

    Design: Corner/validations/sanitation_pass_below_temp_rejected
    """
    station = make_station(requires_autoclave=True)
    tech = make_technician(station["id"])
    payload = create_sanitation_log_payload(station["id"], tech["id"],
                                            cycle_result="PASS", cycle_temp_c=100.0,
                                            hold_minutes=30)
    res = api.create_sanitation_log(payload, make_technician_headers(tech["id"]))
    validate_error(res, "ERR_STERILIZATION_INVALID")


def test_sanitation_pass_short_hold_rejected(api):
    """PRD §3.2: "A log claiming `PASS` is only honored if its `cycle_temp_c` is at
    least 121.0 and its `hold_minutes` is at least 30; a `PASS` claim that fails
    either of these thresholds is physically inconsistent and is rejected with
    `ERR_STERILIZATION_INVALID`."

    Design: Corner/validations/sanitation_pass_short_hold_rejected
    """
    station = make_station(requires_autoclave=True)
    tech = make_technician(station["id"])
    payload = create_sanitation_log_payload(station["id"], tech["id"],
                                            cycle_result="PASS", cycle_temp_c=134.0,
                                            hold_minutes=20)
    res = api.create_sanitation_log(payload, make_technician_headers(tech["id"]))
    validate_error(res, "ERR_STERILIZATION_INVALID")


# ---------------------------------------------------------------------------
# Corner: sanitation freshness derivation
# ---------------------------------------------------------------------------
def test_sanitation_log_pass_recomputes_station_clean(api):
    """PRD §3.2: "When a `PASS` log is accepted, the station's `sanitation_status`
    recomputes to `CLEAN` and its `last_pass_sanitation_at` is stamped with the
    log's `created_at`".

    Design: Corner/endpoints/sanitation_log_pass_recomputes_station_clean
    """
    set_clock("2026-07-16T09:00:00Z")
    station = make_station(requires_autoclave=True)
    tech = make_technician(station["id"])
    record_pass_sanitation(station["id"], tech["id"], cycle_temp_c=134.0,
                           hold_minutes=30)

    got = validate_success(api.get_station(station["id"], FRONT_DESK))
    assert got["sanitation_status"] == "CLEAN"


def test_stale_pass_sanitation_makes_station_dirty(api):
    """PRD §3.2: "If the most recent log is a `PASS` but that elapsed time is 24
    hours or more, the status is `DIRTY` — the boundary is strict, so a pass exactly
    24 hours old is already stale and reads `DIRTY`, while anything under 24 hours
    reads `CLEAN`."

    Design: Corner/calculations/stale_pass_sanitation_makes_station_dirty
    """
    set_clock("2026-07-25T09:00:00Z")
    station = make_station(requires_autoclave=True)
    tech = make_technician(station["id"])
    record_pass_sanitation(station["id"], tech["id"], cycle_temp_c=134.0,
                           hold_minutes=30)
    set_clock("2026-07-26T09:00:00Z")   # exactly 24h later -> stale

    got = validate_success(api.get_station(station["id"], FRONT_DESK))
    assert got["sanitation_status"] == "DIRTY"


# ---------------------------------------------------------------------------
# Difficulty: check-in gated by station sanitation (Appointment -> Station)
# ---------------------------------------------------------------------------
def test_checkin_blocked_when_station_dirty(api):
    """PRD §3.8: "If either the booked service's `requires_sterile_station` is true
    or the station's `requires_autoclave` is true, then the station's
    `sanitation_status` must be `CLEAN` at check-in time; if sterilization is
    required but the station is not clean, the check-in is rejected with
    `ERR_STATION_NOT_STERILE`."

    Design: Difficulty/cross_entity_state_dependency/checkin_gated_by_station_sanitation
    """
    set_clock("2026-04-10T12:00:00Z")
    station = make_station(requires_autoclave=True)        # starts DIRTY, no log
    menu = make_menu_item(category="PEDICURE", base_price_cents=5000,
                          duration_minutes=50, requires_sterile_station=True)
    tech = make_technician(station["id"], license_expiry="2027-01-01T00:00:00Z")
    client = make_client()
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-04-10T13:00:00Z")
    confirm(appt["id"])

    res = api.check_in_appointment(appt["id"], FRONT_DESK)
    validate_error(res, "ERR_STATION_NOT_STERILE")


def test_checkin_succeeds_after_pass_log_cleans_station(api):
    """PRD §3.8: "If either the booked service's `requires_sterile_station` is true
    or the station's `requires_autoclave` is true, then the station's
    `sanitation_status` must be `CLEAN` at check-in time".
    PRD §3.2: "When a `PASS` log is accepted, the station's `sanitation_status`
    recomputes to `CLEAN`".

    Design: Difficulty/cross_entity_state_dependency/checkin_gated_by_station_sanitation
    """
    set_clock("2026-04-10T12:00:00Z")
    station = make_station(requires_autoclave=True)
    menu = make_menu_item(category="PEDICURE", base_price_cents=5000,
                          duration_minutes=50, requires_sterile_station=True)
    tech = make_technician(station["id"], license_expiry="2027-01-01T00:00:00Z")
    client = make_client()
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-04-10T13:00:00Z")
    confirm(appt["id"])
    record_pass_sanitation(station["id"], tech["id"], cycle_temp_c=134.0,
                           hold_minutes=30)

    checked = validate_success(api.check_in_appointment(appt["id"], FRONT_DESK))
    assert checked["booking_status"] == "CHECKED_IN"


# ---------------------------------------------------------------------------
# Corner: license gate isolated
# ---------------------------------------------------------------------------
def test_error_license_expired_triggerable(api):
    """PRD §3.8: "The assigned technician must be fit to work: the technician's
    `status` must be `ACTIVE` and the technician's `license_expiry` must be strictly
    after the current logical clock. A suspended, terminated, or lapsed-license
    technician blocks check-in with `ERR_LICENSE_EXPIRED`."

    Design: Corner/errors/error_license_expired_triggerable
    """
    set_clock("2026-07-18T08:00:00Z")
    station = make_station(requires_autoclave=True)
    menu = make_menu_item(category="PEDICURE", base_price_cents=5000,
                          duration_minutes=50, requires_sterile_station=True)
    tech = make_technician(station["id"], license_expiry="2026-06-01T00:00:00Z")  # expired
    client = make_client()
    # Make the station CLEAN so the sterilization gate is satisfied and only the
    # license gate can fail.
    record_pass_sanitation(station["id"], tech["id"], cycle_temp_c=134.0,
                           hold_minutes=30)
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-07-18T13:00:00Z")
    confirm(appt["id"])
    set_clock("2026-07-18T12:00:00Z")

    res = api.check_in_appointment(appt["id"], FRONT_DESK)
    validate_error(res, "ERR_LICENSE_EXPIRED")


# ---------------------------------------------------------------------------
# Difficulty: priority pair — safety (sterile) vs safety (license) at check-in.
# PRD §3.8 describes both gates but does NOT pin which error wins when both fail,
# so per the error-precedence rule the assertion is relaxed to one-of.
# ---------------------------------------------------------------------------
def test_checkin_both_gates_fail_returns_a_safety_error(api):
    """PRD §3.8: "if sterilization is required but the station is not clean, the
    check-in is rejected with `ERR_STATION_NOT_STERILE`."
    PRD §3.8: "A suspended, terminated, or lapsed-license technician blocks check-in
    with `ERR_LICENSE_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_checkin
    """
    set_clock("2026-03-29T12:00:00Z")
    station = make_station(requires_autoclave=True)        # DIRTY (no PASS log)
    menu = make_menu_item(category="PEDICURE", base_price_cents=5000,
                          duration_minutes=50, requires_sterile_station=True)
    tech = make_technician(station["id"], license_expiry="2026-03-01T00:00:00Z")  # expired
    client = make_client()
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-03-29T13:00:00Z")
    confirm(appt["id"])

    res = api.check_in_appointment(appt["id"], FRONT_DESK)
    validate_error_is_one_of(res, ["ERR_STATION_NOT_STERILE", "ERR_LICENSE_EXPIRED"])


def test_checkin_both_gates_fail_leaves_appointment_confirmed(api):
    """PRD §3.8: "if sterilization is required but the station is not clean, the
    check-in is rejected with `ERR_STATION_NOT_STERILE`."
    PRD §3.8: "A suspended, terminated, or lapsed-license technician blocks check-in
    with `ERR_LICENSE_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_checkin
    """
    set_clock("2026-03-29T12:00:00Z")
    station = make_station(requires_autoclave=True)
    menu = make_menu_item(category="PEDICURE", base_price_cents=5000,
                          duration_minutes=50, requires_sterile_station=True)
    tech = make_technician(station["id"], license_expiry="2026-03-01T00:00:00Z")
    client = make_client()
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-03-29T13:00:00Z")
    confirm(appt["id"])

    res = api.check_in_appointment(appt["id"], FRONT_DESK)
    validate_error_is_one_of(res, ["ERR_STATION_NOT_STERILE", "ERR_LICENSE_EXPIRED"])
    after = validate_success(api.get_appointment(appt["id"], FRONT_DESK))
    assert after["booking_status"] == "CONFIRMED"
