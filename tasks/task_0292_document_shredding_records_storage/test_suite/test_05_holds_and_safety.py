"""Compliance holds, segregation of duties, and the priority ordering between
state, business-safety, and business-temporal checks.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_destruction_witness_headers,
    setup_account_with_rate_card,
    setup_offsite_order_at_plant,
    setup_stored_box,
    setup_ingested_box,
    create_box,
    place_hold,
)
from test_helpers import factories as f

CO = TEST_USERS["compliance_officer_headers"]
AM = TEST_USERS["account_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]


# ===========================================================================
# priority_pair_validation_conflict / purge_state_vs_safety_conflict
# ===========================================================================
def test_purge_state_check_outranks_hold_check(api):
    """PRD §2.10: "The state precondition - that the target is in a state from
    which the requested transition is defined - is checked next and yields the
    transition-specific conflict error from the state machine. Then come the
    business-safety checks: an active compliance hold on the subject
    (ERR_SUBJECT_ON_HOLD)."

    PRD §3.8: "a purge on a box not in STORED is rejected with ERR_BOX_NOT_STORED."

    An INGESTED (never shelved) box with an ACTIVE hold fails with the state
    error ERR_BOX_NOT_STORED, since the state check precedes the hold check.

    Design: Difficulty/priority_pair_validation_conflict/purge_state_vs_safety_conflict
    """
    state = setup_ingested_box(barcode="BX-1", with_rate_card=False)
    place_hold(state["account"]["id"], "RETENTION_BOX", state["box"]["id"], reason="LITIGATION_HOLD")
    validate_error(api.purge_box(state["box"]["id"], AM),
                   ApiErrorId.ERR_BOX_NOT_STORED.value)


def test_purge_ingested_held_box_status_unchanged(api):
    """PRD §3.8: "a purge on a box not in STORED is rejected with
    ERR_BOX_NOT_STORED."

    The rejected purge leaves the INGESTED box unchanged.

    Design: Difficulty/priority_pair_validation_conflict/purge_state_vs_safety_conflict
    """
    state = setup_ingested_box(barcode="BX-1", with_rate_card=False)
    place_hold(state["account"]["id"], "RETENTION_BOX", state["box"]["id"], reason="LITIGATION_HOLD")
    validate_error(api.purge_box(state["box"]["id"], AM),
                   ApiErrorId.ERR_BOX_NOT_STORED.value)
    box = validate_success(api.get_retention_box(state["box"]["id"], AM), 200)
    assert box["status"] == "INGESTED"


# ===========================================================================
# priority_pair_validation_conflict / purge_safety_vs_temporal_conflict
# ===========================================================================
def test_purge_hold_check_outranks_retention_check(api):
    """PRD §3.8: "Purge is gated by two checks evaluated in order: first, that no
    active compliance hold names the box (ERR_SUBJECT_ON_HOLD, checked before the
    retention schedule); and second, when the box has a destroy_after_period set,
    that the account's current_period_index has reached at least that period -
    otherwise the retention clock has not elapsed and the purge is rejected with
    ERR_RETENTION_NOT_ELAPSED."

    A STORED box with both an ACTIVE hold and an unelapsed retention schedule
    (destroy_after_period 5, current period 0) fails with ERR_SUBJECT_ON_HOLD.

    Design: Difficulty/priority_pair_validation_conflict/purge_safety_vs_temporal_conflict
    """
    state = setup_stored_box(barcode="BX-1", destroy_after_period=5, with_rate_card=False)
    place_hold(state["account"]["id"], "RETENTION_BOX", state["box"]["id"], reason="AUDIT_HOLD")
    validate_error(api.purge_box(state["box"]["id"], AM),
                   ApiErrorId.ERR_SUBJECT_ON_HOLD.value)


def test_purge_held_unelapsed_box_status_unchanged(api):
    """PRD §3.10: "While it is ACTIVE, the named subject cannot be destroyed or
    purged ... every one of these is the ERR_SUBJECT_ON_HOLD rejection raised in
    the workflow it guards."

    The rejected purge leaves the held STORED box unchanged.

    Design: Difficulty/priority_pair_validation_conflict/purge_safety_vs_temporal_conflict
    """
    state = setup_stored_box(barcode="BX-1", destroy_after_period=5, with_rate_card=False)
    place_hold(state["account"]["id"], "RETENTION_BOX", state["box"]["id"], reason="AUDIT_HOLD")
    validate_error(api.purge_box(state["box"]["id"], AM),
                   ApiErrorId.ERR_SUBJECT_ON_HOLD.value)
    box = validate_success(api.get_retention_box(state["box"]["id"], AM), 200)
    assert box["status"] == "STORED"


# ===========================================================================
# cross_entity_state_dependency / order_destroy_blocked_by_hold
# ===========================================================================
def test_destroy_blocked_by_active_hold_on_order(api):
    """PRD §3.5: "This is defined only from AT_PLANT (otherwise
    ERR_ORDER_NOT_AT_PLANT), only when no active compliance hold names the order
    (otherwise ERR_SUBJECT_ON_HOLD)."

    An AT_PLANT order under an ACTIVE hold cannot be destroyed; it stays AT_PLANT.

    Design: Difficulty/cross_entity_state_dependency/order_destroy_blocked_by_hold
    """
    state = setup_offsite_order_at_plant(tech_id="tech-1", gross_weight_kg=36.0,
                                         capacity_kg=40, tare_weight_kg=4.0, cadence="ONE_TIME")
    place_hold(state["account"]["id"], "SERVICE_ORDER", state["order"]["id"],
               reason="REGULATORY_FREEZE")
    witness_headers = make_destruction_witness_headers("witness-9")
    validate_error(api.destroy_order(state["order"]["id"], f.destroy_payload("witness-9"),
                                     witness_headers),
                   ApiErrorId.ERR_SUBJECT_ON_HOLD.value)
    order = validate_success(api.get_order(state["order"]["id"], AM), 200)
    assert order["status"] == "AT_PLANT", "unchanged after blocked destroy"


def test_destroy_held_order_status_unchanged(api):
    """PRD §3.10: "While it is ACTIVE, the named subject cannot be destroyed or
    purged ... every one of these is the ERR_SUBJECT_ON_HOLD rejection raised in
    the workflow it guards."

    The held order does not advance to DESTROYED.

    Design: Difficulty/cross_entity_state_dependency/order_destroy_blocked_by_hold
    """
    state = setup_offsite_order_at_plant(tech_id="tech-1", gross_weight_kg=36.0,
                                         capacity_kg=40, tare_weight_kg=4.0, cadence="ONE_TIME")
    place_hold(state["account"]["id"], "SERVICE_ORDER", state["order"]["id"],
               reason="REGULATORY_FREEZE")
    witness_headers = make_destruction_witness_headers("witness-9")
    validate_error(api.destroy_order(state["order"]["id"], f.destroy_payload("witness-9"),
                                     witness_headers),
                   ApiErrorId.ERR_SUBJECT_ON_HOLD.value)
    assert validate_success(api.get_order(state["order"]["id"], AM), 200)["status"] == "AT_PLANT"


# ===========================================================================
# Corner: rbac / destroy_witness_equals_collector_sod_denied
# ===========================================================================
def test_destroy_witness_equal_to_collector_rejected(api):
    """PRD §3.5: "and only when segregation of duties is satisfied: the
    witnessing operator's X-User-ID, supplied on the request as witnessed_by,
    must differ from the order's recorded assigned_tech_id - the collector may not
    also witness - otherwise the request is rejected with
    ERR_SEGREGATION_OF_DUTIES."

    An order with assigned_tech_id tech-1 destroyed by a witness whose id is also
    tech-1 is rejected; the order stays AT_PLANT.

    Design: Corner/rbac/destroy_witness_equals_collector_sod_denied
    """
    state = setup_offsite_order_at_plant(tech_id="tech-1", gross_weight_kg=36.0,
                                         capacity_kg=40, tare_weight_kg=4.0, cadence="ONE_TIME")
    witness_headers = make_destruction_witness_headers("tech-1")
    validate_error(api.destroy_order(state["order"]["id"], f.destroy_payload("tech-1"),
                                     witness_headers),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    order = validate_success(api.get_order(state["order"]["id"], AM), 200)
    assert order["status"] == "AT_PLANT", "unchanged after SoD rejection"
