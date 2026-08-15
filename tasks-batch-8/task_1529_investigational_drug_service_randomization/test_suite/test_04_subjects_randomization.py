"""Subject enrollment, screening/rescreen, slot-driven randomization, and the
site-state randomization gate (PRD §3.5)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    setup_pharmacy, setup_randomized_subject, setup_subject_with_allocated_kit,
    setup_dispensed_subject, register_subject, upload_slots, slot_spec,
    transition_site, get_kit, post_temperature_log,
)
from test_helpers import TEST_USERS, make_pharmacist_headers

SPONSOR = TEST_USERS["sponsor_admin_headers"]


def test_randomize_twice_returns_subject_not_randomizable():
    """PRD §3.5: "Randomizing a subject is the pivotal enrollment act, moving
    them `SCREENING` → `RANDOMIZED`; attempting it on a subject not in
    `SCREENING` is rejected with `ERR_SUBJECT_NOT_RANDOMIZABLE`."

    Design: Corner/state_machines/randomize_twice_returns_subject_not_randomizable
    """
    world = setup_pharmacy(protocol_number="P-SM-4", kit_numbers=("K-R1", "K-R2"),
                           pharmacist_license="L-SM-4")
    result = setup_randomized_subject(world, subject_number="SUB-RT",
                                      slot_kit_numbers=["K-R1", "K-R2"])
    subject = result["subject"]
    assert subject["enrollment_status"] == "RANDOMIZED"
    resp = api_client.randomize_subject(subject["id"], world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_SUBJECT_NOT_RANDOMIZABLE.value, expected_status=409)
    data, meta = validate_paginated(api_client.list_randomization_slots(
        SPONSOR, params={"study_id": world["study"]["id"], "status": "ASSIGNED"}))
    assert meta["total_count"] == 1, "the second randomize must consume no slot"


def test_rescreen_cycle_allowed_once_then_limit():
    """PRD §3.5: "Rescreening moves them back `SCREEN_FAILED` → `SCREENING`,
    but only once: the transition requires `rescreen_count` to still be zero,
    increments it by one, and a second rescreen attempt is rejected with
    `ERR_RESCREEN_LIMIT_EXCEEDED`."

    Design: Corner/state_machines/rescreen_cycle_allowed_once_then_limit
    """
    world = setup_pharmacy(protocol_number="P-SM-7", kit_numbers=(),
                           pharmacist_license="L-SM-7")
    subject = register_subject(world["site"]["id"], "SUB-RS", world["pharmacist"]["id"])
    headers = world["pharmacist_headers"]
    get_success_data(api_client.transition_subject(
        subject["id"], {"to": "SCREEN_FAILED", "reason": "labs"}, headers))
    rescreened = get_success_data(api_client.transition_subject(
        subject["id"], {"to": "SCREENING"}, headers))
    assert rescreened["enrollment_status"] == "SCREENING"
    assert rescreened["rescreen_count"] == 1
    get_success_data(api_client.transition_subject(
        subject["id"], {"to": "SCREEN_FAILED", "reason": "labs again"}, headers))
    resp = api_client.transition_subject(subject["id"], {"to": "SCREENING"}, headers)
    validate_error(resp, ApiErrorId.ERR_RESCREEN_LIMIT_EXCEEDED.value, expected_status=422)
    final = get_success_data(api_client.get_subject(subject["id"], SPONSOR))
    assert final["enrollment_status"] == "SCREEN_FAILED"


def test_subject_complete_blocked_with_active_dispensing():
    """PRD §3.5: "Moving a `RANDOMIZED` subject to `COMPLETED` or to `WITHDRAWN`
    is blocked while any of the subject's dispensing records remains `ACTIVE`,
    surfacing `ERR_ACTIVE_DISPENSING_EXISTS`; both destination states are
    terminal."

    Design: Corner/state_machines/subject_complete_blocked_with_active_dispensing
    """
    world = setup_pharmacy(protocol_number="P-SM-8", kit_numbers=("K-CP",),
                           pharmacist_license="L-SM-8")
    disp = setup_dispensed_subject(world, subject_number="SUB-CP", quantity=4)
    assert disp["record"]["status"] == "ACTIVE"
    resp = api_client.transition_subject(disp["subject"]["id"], {"to": "COMPLETED"},
                                         world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_ACTIVE_DISPENSING_EXISTS.value, expected_status=422)
    final = get_success_data(api_client.get_subject(disp["subject"]["id"], SPONSOR))
    assert final["enrollment_status"] == "RANDOMIZED"


def test_randomize_selector_picks_lowest_sequence_not_payload_order():
    """PRD §3.5: "The selected slot is the one with the lowest
    `sequence_number`, ties broken by the earlier `created_at`."

    Design: Corner/calculations/randomize_selector_picks_lowest_sequence_not_payload_order
    """
    world = setup_pharmacy(protocol_number="P-CAL-2", kit_numbers=("K-SEL-HI", "K-SEL-LO"),
                           pharmacist_license="L-CAL-2")
    # Upload seq 5 first, then seq 2: payload order must not matter.
    result = setup_randomized_subject(world, subject_number="SUB-SEL", slot_specs=[
        slot_spec(5, "K-SEL-HI", arm_code="PBO"),
        slot_spec(2, "K-SEL-LO", arm_code="TRT-A"),
    ])
    subject = result["subject"]
    kits = {k["kit_number"]: get_kit(k["id"]) for k in world["kits"]}
    assert kits["K-SEL-LO"]["status"] == "ALLOCATED"
    assert kits["K-SEL-LO"]["allocated_subject_id"] == subject["id"]
    assert kits["K-SEL-HI"]["status"] == "AVAILABLE", (
        "the seq-5 slot stays UNASSIGNED and its kit untouched"
    )


def test_randomize_with_empty_stratum_pool_returns_no_slot():
    """PRD §3.5: "an `UNASSIGNED` slot must exist for this study in the
    subject's `stratum` (`ERR_NO_RANDOMIZATION_SLOT`)".

    Design: Corner/calculations/randomize_with_empty_stratum_pool_returns_no_slot
    """
    world = setup_pharmacy(protocol_number="P-CAL-3", kit_numbers=("K-HR",),
                           pharmacist_license="L-CAL-3")
    slots = upload_slots(world["study"]["id"], world["study_version"],
                         [slot_spec(1, "K-HR", stratum="STANDARD", arm_code="TRT-A")])
    subject = register_subject(world["site"]["id"], "SUB-HR", world["pharmacist"]["id"],
                               stratum="HIGH_RISK")
    resp = api_client.randomize_subject(subject["id"], world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_RANDOMIZATION_SLOT.value, expected_status=422)
    assert get_success_data(api_client.get_subject(subject["id"], SPONSOR))["enrollment_status"] == "SCREENING"
    assert get_success_data(api_client.get_randomization_slot(slots[0]["id"], SPONSOR))["status"] == "UNASSIGNED"
    assert get_kit(world["kits"][0]["id"])["status"] == "AVAILABLE"


def test_randomize_with_quarantined_slot_kit_returns_kit_quarantined_excursion():
    """PRD §3.5: "That slot's `kit_number` must then resolve to a kit at the
    subject's own site in `AVAILABLE` status — with an important priority
    nuance: if the kit resolves but sits in `QUARANTINED_EXCURSION`, the
    rejection is the safety error `ERR_KIT_QUARANTINED_EXCURSION`, evaluated at
    the safety gate (priority 7), whereas any other non-`AVAILABLE` resolution
    is the later constraint error `ERR_SLOT_KIT_UNAVAILABLE` (priority 9)."

    Design: Corner/validations/randomize_with_quarantined_slot_kit_returns_kit_quarantined_excursion
    """
    world = setup_pharmacy(protocol_number="P-VAL-14", kit_numbers=("K-QQ",),
                           pharmacist_license="L-VAL-14")
    slots = upload_slots(world["study"]["id"], world["study_version"],
                         [slot_spec(1, "K-QQ", arm_code="TRT-A")])
    post_temperature_log(world["site"]["id"], 9.0, world["pharmacist"]["id"], source="MANUAL")
    assert get_kit(world["kits"][0]["id"])["status"] == "QUARANTINED_EXCURSION"
    subject = register_subject(world["site"]["id"], "SUB-QQ", world["pharmacist"]["id"])
    resp = api_client.randomize_subject(subject["id"], world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_KIT_QUARANTINED_EXCURSION.value, expected_status=422)
    assert get_success_data(api_client.get_subject(subject["id"], SPONSOR))["enrollment_status"] == "SCREENING"
    assert get_success_data(api_client.get_randomization_slot(slots[0]["id"], SPONSOR))["status"] == "UNASSIGNED"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / subject_randomize_blocked_when_site_on_hold
# ---------------------------------------------------------------------------

def _world_with_site_on_hold():
    """Kit AVAILABLE + slot uploaded + SCREENING subject, then the site is
    placed ON_HOLD while the study stays ACTIVE."""
    world = setup_pharmacy(protocol_number="P-XEN-2", kit_numbers=("K-G",),
                           pharmacist_license="L-XEN2-1",
                           lot_overrides={"lot_number": "LOT-XEN-2"})
    slots = upload_slots(world["study"]["id"], world["study_version"],
                         [slot_spec(1, "K-G", arm_code="TRT-A")])
    world["study_version"] += 1
    subject = register_subject(world["site"]["id"], "SUB-G", world["pharmacist"]["id"])
    transition_site(world["site"]["id"], "ON_HOLD")
    return world, subject, slots


def test_randomize_blocked_when_site_on_hold():
    """PRD §3.5: "The gates run in the global order of §2.6: the subject's site
    must be `ACTIVE` (`ERR_SITE_NOT_ACTIVE`), the site's study must be `ACTIVE`
    (`ERR_STUDY_NOT_ACTIVE`), and an `UNASSIGNED` slot must exist for this study
    in the subject's `stratum` (`ERR_NO_RANDOMIZATION_SLOT`)."

    Design: Difficulty/cross_entity_state_dependency/subject_randomize_blocked_when_site_on_hold
    """
    world, subject, slots = _world_with_site_on_hold()
    resp = api_client.randomize_subject(subject["id"], world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_SITE_NOT_ACTIVE.value, expected_status=409)
    assert get_success_data(api_client.get_subject(subject["id"], SPONSOR))["enrollment_status"] == "SCREENING"


def test_randomize_blocked_when_site_on_hold_consumes_nothing():
    """PRD §3.5: "On success the subject's `randomized_at` is stamped from the
    logical clock, the slot moves `UNASSIGNED` → `ASSIGNED` with
    `assigned_subject_id` set to the subject, the kit moves `AVAILABLE` →
    `ALLOCATED` with `allocated_subject_id` set to the subject, and the study's
    `randomized_subject_count` increases by one". A rejected randomize performs
    none of these.

    Design: Difficulty/cross_entity_state_dependency/subject_randomize_blocked_when_site_on_hold
    """
    world, subject, slots = _world_with_site_on_hold()
    api_client.randomize_subject(subject["id"], world["pharmacist_headers"])
    assert get_success_data(api_client.get_randomization_slot(slots[0]["id"], SPONSOR))["status"] == "UNASSIGNED"
    assert get_kit(world["kits"][0]["id"])["status"] == "AVAILABLE"
    study = get_success_data(api_client.get_study(world["study"]["id"], SPONSOR))
    assert study["randomized_subject_count"] == 0
