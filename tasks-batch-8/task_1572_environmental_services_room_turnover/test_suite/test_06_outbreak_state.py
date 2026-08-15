"""OutbreakEvent state machine claims (state errors, uniqueness, lift pinning)."""
from test_helpers import (
    ApiErrorId,
    CLOCK_T0800,
    api_client,
    create_bed_payload,
    create_clean_request_payload,
    create_outbreak_event_payload,
    create_unit_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import create_all_standards

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
IP = TEST_USERS["ip_headers"]
ANY = TEST_USERS["any_headers"]


def test_outbreak_state_errors_and_active_uniqueness(api):
    """PRD §3.8: "A declared event that should never have been filed can be
    **cancelled** while still `DECLARED`; any other state rejects both
    cancellation and activation with `ERR_OUTBREAK_INVALID_STATE`."
    PRD §3.8: "It requires `DECLARED` status and requires that no other event
    for the same unit is already `ACTIVE` (`ERR_OUTBREAK_ALREADY_ACTIVE`)."
    PRD §3.8: "**Lifting** an `ACTIVE` outbreak stamps `lifted_at`, moves the
    event to `LIFTED`, and recomputes the unit's posture."

    Design: Corner/state_machines/outbreak_state_errors_and_active_uniqueness
    """
    set_clock(CLOCK_T0800)
    unit = get_success_data(api.create_unit(create_unit_payload(), ADMIN))
    e1 = get_success_data(
        api.create_outbreak_event(
            create_outbreak_event_payload(unit_id=unit["id"], pathogen_class="C_DIFF"),
            IP,
        )
    )
    e2 = get_success_data(
        api.create_outbreak_event(
            create_outbreak_event_payload(unit_id=unit["id"], pathogen_class="MRSA"), IP
        )
    )

    # Activate e1 successfully.
    activated = validate_success(api.activate_outbreak_event(e1["id"], IP))
    assert activated["status"] == "ACTIVE"

    # Re-activate ACTIVE e1.
    r_reactivate = api.activate_outbreak_event(e1["id"], IP)
    validate_error(r_reactivate, ApiErrorId.ERR_OUTBREAK_INVALID_STATE)

    # Second event activate while e1 ACTIVE.
    r_second = api.activate_outbreak_event(e2["id"], IP)
    validate_error(r_second, ApiErrorId.ERR_OUTBREAK_ALREADY_ACTIVE)

    # Lift from DECLARED.
    r_lift_declared = api.lift_outbreak_event(e2["id"], IP)
    validate_error(r_lift_declared, ApiErrorId.ERR_OUTBREAK_INVALID_STATE)

    # Cancel from ACTIVE.
    r_cancel_active = api.cancel_outbreak_event(e1["id"], IP)
    validate_error(r_cancel_active, ApiErrorId.ERR_OUTBREAK_INVALID_STATE)

    # Lift e1, then cancel e2 (DECLARED) — both valid.
    lifted = validate_success(api.lift_outbreak_event(e1["id"], IP))
    assert lifted["status"] == "LIFTED"
    cancelled = validate_success(api.cancel_outbreak_event(e2["id"], IP))
    assert cancelled["status"] == "CANCELLED"

    unit_after = validate_success(api.get_unit(unit["id"], ANY))
    assert unit_after["outbreak_posture"] == "NORMAL"
    assert unit_after["version"] == 3


def test_outbreak_lift_preserves_in_flight_pins(api):
    """PRD §3.8: "Lifting is explicitly non-retroactive — in-flight requests
    keep their pinned standards and due times exactly as computed, and only
    future creations and future pins observe the returned `NORMAL` posture."
    PRD §3.3: "Separately, every read of a request exposes
    `current_estimate_minutes`: the same formula evaluated against the clean
    type's *current* standard row and the unit's *current* posture."

    Design: Corner/state_machines/outbreak_lift_preserves_in_flight_pins
    """
    set_clock(CLOCK_T0800)
    unit = get_success_data(api.create_unit(create_unit_payload(), ADMIN))
    create_all_standards()
    bi1 = get_success_data(
        api.create_bed(
            create_bed_payload(unit_id=unit["id"], bed_code="BI1", bed_kind="ISOLATION"),
            ADMIN,
        )
    )
    bi2 = get_success_data(
        api.create_bed(
            create_bed_payload(unit_id=unit["id"], bed_code="BI2", bed_kind="ISOLATION"),
            ADMIN,
        )
    )
    r1 = get_success_data(
        api.create_clean_request(
            create_clean_request_payload(bed_id=bi1["id"], clean_type="ISOLATION"),
            DISPATCHER,
        )
    )
    assert r1["sla_target_minutes"] == 60

    ob = get_success_data(
        api.create_outbreak_event(
            create_outbreak_event_payload(unit_id=unit["id"], pathogen_class="NOROVIRUS"),
            IP,
        )
    )
    get_success_data(api.activate_outbreak_event(ob["id"], IP))

    # Lift, then create a fresh request.
    get_success_data(api.lift_outbreak_event(ob["id"], IP))
    r2 = get_success_data(
        api.create_clean_request(
            create_clean_request_payload(bed_id=bi2["id"], clean_type="ISOLATION"),
            DISPATCHER,
        )
    )

    unit_after = validate_success(api.get_unit(unit["id"], ANY))
    assert unit_after["outbreak_posture"] == "NORMAL"

    r1_after = validate_success(api.get_clean_request(r1["id"], ANY))
    assert r1_after["clean_type"] == "TERMINAL"
    assert r1_after["sla_target_minutes"] == 180
    assert r1_after["current_estimate_minutes"] == 90

    assert r2["sla_target_minutes"] == 60
    assert r2["pinned_with_outbreak"] is False
