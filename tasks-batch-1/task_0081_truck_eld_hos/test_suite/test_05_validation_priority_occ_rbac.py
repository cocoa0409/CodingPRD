"""Validation ordering, OCC concurrency, and RBAC (PRD §2.1, §2.6, §2.10, §3).

Covers difficulty priority_pair_validation_conflict plus corner validations / errors /
rbac / cross_cutting_complexity_layers / consistency_model instances.
"""
from test_helpers import fixtures, factories
from test_helpers.test_users import make_driver_headers, TEST_USERS
from test_helpers import validate_success, validate_error, NON_EXISTENT_UUID


ADMIN = TEST_USERS["carrier_admin_headers"]
OFFICER = TEST_USERS["safety_officer_headers"]


# =====================================================================
# Difficulty / priority_pair_validation_conflict
# =====================================================================
def test_state_invalid_beats_pc_safety_on_double_markerror(api):
    """PRD §3.6: "This is permitted only while the event's record_status is ACTIVE; from any
    other record status it is rejected with ERR_INVALID_STATE."
    PRD §2.10: "The system then confirms the target resource is in a state from which the
    requested transition is defined (ERR_INVALID_STATE), after which the operation-specific
    business rules described in Section 3 apply in the order set out there".

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_beats_business_safety_pc_not_authorized
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z",
                                        driver_overrides={"pc_authorized": False})
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    stream = fixtures.make_stream(setup)
    evt = stream.append("DRIVING", "2026-06-01T06:30:00Z")
    fixtures.mark_error(evt["id"])  # now INACTIVE_ERROR

    # Second mark-error on the already INACTIVE_ERROR event.
    v = fixtures.get_event(evt["id"])["version"]
    resp = api.mark_error_duty_event(evt["id"], factories.mark_error_payload(v), ADMIN)
    validate_error(resp, "ERR_INVALID_STATE")


def test_state_invalid_returned_with_409_on_double_markerror(api):
    """PRD §3.6: "This is permitted only while the event's record_status is ACTIVE; from any
    other record status it is rejected with ERR_INVALID_STATE."
    PRD §5: the error catalogue maps ERR_INVALID_STATE to HTTP 409 Conflict.

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_beats_business_safety_pc_not_authorized
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z",
                                        driver_overrides={"pc_authorized": False})
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    stream = fixtures.make_stream(setup)
    evt = stream.append("DRIVING", "2026-06-01T06:30:00Z")
    fixtures.mark_error(evt["id"])
    v = fixtures.get_event(evt["id"])["version"]
    resp = api.mark_error_duty_event(evt["id"], factories.mark_error_payload(v), ADMIN)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


def test_reference_not_found_beats_event_out_of_order(api):
    """PRD §2.10: "The system then confirms that every resource identifier in the path
    exists (ERR_NOT_FOUND), then that every foreign key in the body resolves
    (ERR_REFERENCE_NOT_FOUND)."
    PRD §3.3: "The event_time must be strictly greater than the event_time of the latest
    surviving event for this driver ... an event_time that is not strictly later is rejected
    with ERR_EVENT_OUT_OF_ORDER."

    Design: Difficulty/priority_pair_validation_conflict/existence_reference_beats_business_temporal_out_of_order
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    stream = fixtures.make_stream(setup)
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T10:00:00Z")  # latest at 10:00

    v = fixtures.driver_version(d_id)
    # device_id does not exist AND event_time 09:00 is out of order.
    payload = factories.create_duty_event_payload(
        d_id, "00000000-0000-4000-8000-000000000000", "DRIVING", "2026-06-01T09:00:00Z", v)
    resp = api.create_duty_event(payload, make_driver_headers(d_id))
    validate_error(resp, "ERR_REFERENCE_NOT_FOUND")


def test_reference_not_found_returned_with_404_over_temporal(api):
    """PRD §2.7: "when any of these references a resource that does not exist, the request is
    rejected with ERR_REFERENCE_NOT_FOUND."
    PRD §5: the error catalogue maps ERR_REFERENCE_NOT_FOUND to HTTP 404 Not Found.

    Design: Difficulty/priority_pair_validation_conflict/existence_reference_beats_business_temporal_out_of_order
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    stream = fixtures.make_stream(setup)
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T10:00:00Z")
    v = fixtures.driver_version(d_id)
    payload = factories.create_duty_event_payload(
        d_id, "00000000-0000-4000-8000-000000000000", "DRIVING", "2026-06-01T08:00:00Z", v)
    resp = api.create_duty_event(payload, make_driver_headers(d_id))
    validate_error(resp, "ERR_REFERENCE_NOT_FOUND", expected_status=404)


# =====================================================================
# Corner / validations
# =====================================================================
def test_pc_without_authorization_rejected(api):
    """PRD §3.3: "When it is PERSONAL_CONVEYANCE, the driver must have pc_authorized set to
    true and the duty_status must be either DRIVING or OFF_DUTY; a Personal Conveyance
    annotation that fails either condition is rejected with ERR_PC_NOT_AUTHORIZED."

    Design: Corner/validations/pc_without_authorization_rejected
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z",
                                        driver_overrides={"pc_authorized": False})
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    v = fixtures.driver_version(d_id)
    payload = factories.create_duty_event_payload(
        d_id, dev_id, "DRIVING", "2026-06-01T06:30:00Z", v,
        special_driving_category="PERSONAL_CONVEYANCE", annotation="Driving home.")
    resp = api.create_duty_event(payload, make_driver_headers(d_id))
    validate_error(resp, "ERR_PC_NOT_AUTHORIZED")


def test_annotation_required_on_yard_move(api):
    """PRD §3.3: "Whenever the special_driving_category is anything other than NONE, or
    whenever edited_from_event_id is supplied, a non-empty annotation is required, and its
    absence is rejected with ERR_ANNOTATION_REQUIRED."

    Design: Corner/validations/annotation_required_on_special_category
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    v = fixtures.driver_version(d_id)
    payload = factories.create_duty_event_payload(
        d_id, dev_id, "DRIVING", "2026-06-01T06:30:00Z", v,
        special_driving_category="YARD_MOVE")
    resp = api.create_duty_event(payload, make_driver_headers(d_id))
    validate_error(resp, "ERR_ANNOTATION_REQUIRED")


def test_edit_target_inactive_rejected(api):
    """PRD §3.6: "The edited_from_event_id must reference an ACTIVE event belonging to the
    same driver; a target that is not an active event of that driver is rejected with
    ERR_EDIT_TARGET_INVALID."

    Design: Corner/validations/edit_target_inactive_rejected
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    stream = fixtures.make_stream(setup)
    evt = stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z")
    fixtures.mark_error(evt["id"])  # event becomes INACTIVE_ERROR

    v = fixtures.driver_version(d_id)
    payload = factories.create_duty_event_payload(
        d_id, dev_id, "DRIVING", "2026-06-01T06:05:00Z", v,
        edited_from_event_id=evt["id"], annotation="Trying to edit a dead record.")
    resp = api.create_duty_event(payload, make_driver_headers(d_id))
    validate_error(resp, "ERR_EDIT_TARGET_INVALID")


def test_certify_future_day_rejected(api):
    """PRD §3.8: "A log whose log_date is in the future relative to the server's current
    clock cannot be certified and is rejected with ERR_CANNOT_CERTIFY_FUTURE."

    Design: Corner/validations/certify_future_day_rejected
    """
    driver = fixtures.create_driver()
    fixtures.pin_clock("2026-06-01T12:00:00Z")
    log = fixtures.open_daily_log(driver["id"], "2026-06-05")
    resp = api.certify_daily_log(log["id"], make_driver_headers(driver["id"]))
    validate_error(resp, "ERR_CANNOT_CERTIFY_FUTURE")
    after = validate_success(api.get_daily_log(log["id"], ADMIN), 200)
    assert after["certification_status"] == "UNCERTIFIED"


def test_duplicate_approved_adverse_claim_rejected(api):
    """PRD §3.9: "It also requires that no other APPROVED claim already exist for the same
    driver_id and log_date pair; a second approved claim for that day is rejected with
    ERR_DUPLICATE_ADVERSE_CLAIM."

    Design: Corner/validations/duplicate_approved_adverse_claim_rejected
    """
    driver = fixtures.create_driver()
    d_id = driver["id"]
    claim1 = fixtures.file_adverse_claim(d_id, "2026-06-01", reason="WEATHER", narrative="Ice storm.")
    claim2 = fixtures.file_adverse_claim(d_id, "2026-06-01", reason="ROAD_CLOSURE", narrative="Bridge out.")
    fixtures.approve_adverse_claim(claim1["id"], claim1["version"])

    resp = api.approve_adverse_claim(claim2["id"], factories.approve_claim_payload(claim2["version"]), OFFICER)
    validate_error(resp, "ERR_DUPLICATE_ADVERSE_CLAIM")
    after = validate_success(api.get_adverse_claim(claim2["id"], OFFICER), 200)
    assert after["status"] == "PENDING"


# =====================================================================
# Corner / errors
# =====================================================================
def test_reference_not_found_on_duty_event_bad_driver(api):
    """PRD §2.7: "Foreign-key identifiers supplied in a request body — a driver_id,
    device_id, vehicle_id, trigger_event_id, or edited_from_event_id — are a separate concern:
    when any of these references a resource that does not exist, the request is rejected with
    ERR_REFERENCE_NOT_FOUND."

    Design: Corner/errors/reference_not_found_on_duty_event_bad_driver
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    dev_id = setup["device_id"]
    payload = factories.create_duty_event_payload(
        "11111111-1111-4111-8111-111111111111", dev_id, "DRIVING", "2026-06-01T06:30:00Z",
        setup["driver"]["version"])
    resp = api.create_duty_event(payload, make_driver_headers(setup["driver_id"]))
    validate_error(resp, "ERR_REFERENCE_NOT_FOUND")


def test_stale_version_error_on_duty_event_append(api):
    """PRD §2.6: "When expected_driver_version does not equal the driver's current version,
    the append is rejected with ERR_STALE_VERSION (HTTP 412) before any event is recorded."

    Design: Corner/errors/stale_version_error_on_duty_event_append_active
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    v0 = fixtures.driver_version(d_id)
    # First append bumps Driver.version.
    p1 = factories.create_duty_event_payload(d_id, dev_id, "ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z", v0)
    validate_success(api.create_duty_event(p1, make_driver_headers(d_id)), 201)
    # Second append reuses stale v0.
    p2 = factories.create_duty_event_payload(d_id, dev_id, "DRIVING", "2026-06-01T06:30:00Z", v0)
    resp = api.create_duty_event(p2, make_driver_headers(d_id))
    validate_error(resp, "ERR_STALE_VERSION")


# =====================================================================
# Corner / rbac
# =====================================================================
def test_driver_cannot_create_driver(api):
    """PRD §2.1: "A well-authenticated request whose role is not permitted to perform the
    requested operation is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/driver_cannot_create_driver
    """
    driver = fixtures.create_driver()
    resp = api.create_driver(factories.create_driver_payload(full_name="Sneaky"),
                             make_driver_headers(driver["id"]))
    validate_error(resp, "ERR_UNAUTHORIZED")


def test_carrieradmin_cannot_approve_adverse_claim(api):
    """PRD §2.1: "A well-authenticated request whose role is not permitted to perform the
    requested operation is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/carrieradmin_cannot_approve_adverse_claim
    """
    driver = fixtures.create_driver()
    claim = fixtures.file_adverse_claim(driver["id"], "2026-06-01", reason="WEATHER", narrative="Fog.")
    resp = api.approve_adverse_claim(claim["id"], factories.approve_claim_payload(claim["version"]), ADMIN)
    validate_error(resp, "ERR_UNAUTHORIZED")
    after = validate_success(api.get_adverse_claim(claim["id"], OFFICER), 200)
    assert after["status"] == "PENDING"


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request missing the role header, carrying a role outside this set, or
    omitting X-User-ID where the acting role requires it is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    driver = fixtures.create_driver()
    resp = api.get_driver(driver["id"], {"Content-Type": "application/json"})
    validate_error(resp, "ERR_UNAUTHENTICATED")


def test_driver_cannot_append_event_for_another_driver(api):
    """PRD §2.1: "A Driver may therefore act only on their own duty events, daily logs, and
    adverse-conditions claims; acting on a resource owned by another driver is rejected with
    ERR_UNAUTHORIZED."

    Design: Corner/rbac/driver_cannot_append_event_for_another_driver
    """
    vehicle = fixtures.create_vehicle()
    device = fixtures.create_device(vehicle["id"])
    d1 = fixtures.create_driver()
    d2 = fixtures.create_driver()
    fixtures.pin_clock("2026-06-01T12:00:00Z")
    fixtures.login(device["id"], d1["id"])

    payload = factories.create_duty_event_payload(
        d1["id"], device["id"], "DRIVING", "2026-06-01T06:30:00Z", d1["version"])
    # Acting as D2 against D1's driver_id.
    resp = api.create_duty_event(payload, make_driver_headers(d2["id"]))
    validate_error(resp, "ERR_UNAUTHORIZED")


# =====================================================================
# Corner / cross_cutting_complexity_layers — OCC
# =====================================================================
def test_occ_stale_version_on_second_duty_append(api):
    """PRD §2.6: "a second append still carrying the pre-append version is operating on a
    stale view of the driver's clocks. When expected_driver_version does not equal the
    driver's current version, the append is rejected with ERR_STALE_VERSION (HTTP 412) before
    any event is recorded."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_second_duty_append
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    v0 = fixtures.driver_version(d_id)
    validate_success(api.create_duty_event(
        factories.create_duty_event_payload(d_id, dev_id, "ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z", v0),
        make_driver_headers(d_id)), 201)
    resp = api.create_duty_event(
        factories.create_duty_event_payload(d_id, dev_id, "DRIVING", "2026-06-01T06:30:00Z", v0),
        make_driver_headers(d_id))
    validate_error(resp, "ERR_STALE_VERSION")


def test_occ_correct_version_succeeds_and_increments(api):
    """PRD §2.6: "Appending a duty status event requires expected_driver_version to equal the
    acting driver's current version."
    PRD §2.4: "version, an integer that starts at 1 on creation and increments by exactly one
    on every mutation."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    v0 = fixtures.driver_version(d_id)
    validate_success(api.create_duty_event(
        factories.create_duty_event_payload(d_id, dev_id, "ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z", v0),
        make_driver_headers(d_id)), 201)
    v1 = fixtures.driver_version(d_id)
    validate_success(api.create_duty_event(
        factories.create_duty_event_payload(d_id, dev_id, "DRIVING", "2026-06-01T06:30:00Z", v1),
        make_driver_headers(d_id)), 201)
    after = fixtures.get_driver(d_id)
    assert after["version"] == v1 + 1, f"expected {v1 + 1}, got {after['version']}"


def test_occ_stale_version_on_adverse_claim_approve(api):
    """PRD §2.6: "Approving an adverse-conditions claim requires
    expected_adverseconditionsclaim_version to equal that claim's current version; if the
    claim's version has advanced since the reviewer last read it, the approval is rejected
    with ERR_STALE_VERSION (HTTP 412) before any clock recomputation runs."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_adverse_claim_approve
    """
    driver = fixtures.create_driver()
    claim = fixtures.file_adverse_claim(driver["id"], "2026-06-01", reason="WEATHER", narrative="Hail.")
    resp = api.approve_adverse_claim(
        claim["id"], factories.approve_claim_payload(claim["version"] - 1), OFFICER)
    validate_error(resp, "ERR_STALE_VERSION")
    after = validate_success(api.get_adverse_claim(claim["id"], OFFICER), 200)
    assert after["status"] == "PENDING"


# =====================================================================
# Corner / consistency_model
# =====================================================================
def test_immediate_visibility_of_clocks_after_append(api):
    """PRD §2.5: "large portions of a resource's state are computed, not stored as client
    input, and are reconciled atomically whenever the underlying event stream changes."
    PRD §3.3: "It then runs the clock recomputation and the violation scan described in
    Section 3.4, refreshing the driver's current_duty_status and cycle_on_duty_minutes".

    Design: Corner/consistency_model/immediate_visibility_of_clocks_in_append_response_path
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    v0 = fixtures.driver_version(d_id)
    validate_success(api.create_duty_event(
        factories.create_duty_event_payload(d_id, dev_id, "ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z", v0),
        make_driver_headers(d_id)), 201)
    v1 = fixtures.driver_version(d_id)
    validate_success(api.create_duty_event(
        factories.create_duty_event_payload(d_id, dev_id, "DRIVING", "2026-06-01T06:30:00Z", v1),
        make_driver_headers(d_id)), 201)
    after = fixtures.get_driver(d_id)
    assert after["cycle_on_duty_minutes"] == 30, (
        f"closed ON_DUTY interval (30 min) reflected at once, got {after['cycle_on_duty_minutes']}"
    )
