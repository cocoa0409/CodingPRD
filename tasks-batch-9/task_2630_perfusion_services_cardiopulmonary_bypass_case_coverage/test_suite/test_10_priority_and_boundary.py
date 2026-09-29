"""Two conflicting-priority pairs and two boundaries: one numeric, one cardinal."""
from test_helpers import (
    add_case,
    add_device,
    add_perfusionist,
    add_slot,
    ADMIN_HEADERS,
    api_client,
    assert_case_dimensions,
    assert_cents,
    assert_contract_ledger,
    assert_device_state,
    assert_error_envelope,
    assign_perfusionist,
    base_setup,
    build_assignment,
    build_pack_configuration,
    capture_device_event,
    close_case,
    configure_pack,
    create_case,
    create_ce_activity,
    create_certification,
    create_contract,
    create_perfusionist,
    create_preference_card,
    create_slot,
    create_surgeon,
    end_bypass,
    make_chief_perfusionist_headers,
    make_perfusionist_headers,
    open_checklist,
    read_case,
    read_contract,
    read_device,
    read_perfusionist,
    set_clock,
    setup_verified_setup,
    staffed_setup,
    start_bypass,
    validate_error,
    validate_paginated,
    validate_success,
    verify_checklist,
)


def test_the_case_state_row_masks_the_device_fallback_row_on_start_bypass():
    """Losing the standby answers on the safety row; losing the primary flips the answer to state.

    PRD 3.7: A parallel variant of the second link reaches every case naming the alarmed machine as its **standby** in those same two states, and it is deliberately gentler: such a case keeps its `bypass_status` and keeps its `setup_verified_at`, clears only its `backup_device_id`, and raises `readiness_flag` to `DEVICE_FALLBACK_REQUIRED`.
    PRD 3.7: A case whose primary machine was lost is back in `STAFFED`, so an attempt to go on pump reports `ERR_CASE_NOT_SETUP_VERIFIED` — the state check at rung 30 fires first and masks the flag check at rung 44.
    PRD 3.7: A case that lost only its standby is still `SETUP_VERIFIED`, so rung 30 passes and the attempt reports `ERR_DEVICE_FALLBACK_REQUIRED` instead.

    Design: Difficulty/priority_pair_validation_conflict/case_state_beats_device_fallback_safety_on_start_bypass
    """
    env = setup_verified_setup(checklist_overrides={"hematocrit_pct": 26})
    case_id = env["case"]["id"]
    assert env["case"]["readiness_flag"] == "NONE"

    capture_device_event(
        env["d2"]["id"], "ALARM_CRITICAL", detail="standby pump self-test latched an alarm"
    )
    standby_lost = read_case(case_id)
    assert standby_lost["bypass_status"] == "SETUP_VERIFIED", (
        "the standby-side link is the gentler one and leaves the clinical state alone"
    )
    assert standby_lost["readiness_flag"] == "DEVICE_FALLBACK_REQUIRED"
    assert standby_lost["backup_device_id"] is None
    assert standby_lost["setup_verified_at"] is not None

    safety_only = api_client.start_bypass(case_id, env["p1_headers"])
    validate_error(safety_only, "ERR_DEVICE_FALLBACK_REQUIRED", 409)
    assert_error_envelope(safety_only, "ERR_DEVICE_FALLBACK_REQUIRED")

    capture_device_event(
        env["d1"]["id"], "ALARM_CRITICAL", detail="primary pump arterial alarm latched"
    )
    primary_lost = read_case(case_id)
    assert primary_lost["bypass_status"] == "STAFFED"
    assert primary_lost["readiness_flag"] == "DEVICE_FALLBACK_REQUIRED"

    state_wins = api_client.start_bypass(case_id, env["p1_headers"])
    validate_error(state_wins, "ERR_CASE_NOT_SETUP_VERIFIED", 409)
    assert state_wins.json()["data"]["error_id"] != "ERR_DEVICE_FALLBACK_REQUIRED", (
        "the state row is judged first and masks the still-raised flag"
    )
    assert read_case(case_id)["bypass_started_at"] is None


def test_a_fresh_pack_configuration_clears_both_rows_and_the_pump_opens():
    """With the state restored and the flag cleared, neither row of the pair answers.

    PRD 3.7: A case whose primary machine was lost is back in `STAFFED`, so an attempt to go on pump reports `ERR_CASE_NOT_SETUP_VERIFIED` — the state check at rung 30 fires first and masks the flag check at rung 44.
    PRD 3.7: The flag itself is cleared only by a fresh pack configuration, which is available only while the case is `STAFFED`, or by cancelling the case.

    Design: Difficulty/priority_pair_validation_conflict/case_state_beats_device_fallback_safety_on_start_bypass
    """
    env = setup_verified_setup(checklist_overrides={"hematocrit_pct": 26})
    case_id = env["case"]["id"]

    capture_device_event(
        env["d1"]["id"], "ALARM_CRITICAL", detail="primary pump arterial alarm latched"
    )
    reverted = read_case(case_id)
    assert reverted["bypass_status"] == "STAFFED"
    assert reverted["readiness_flag"] == "DEVICE_FALLBACK_REQUIRED"
    validate_error(
        api_client.start_bypass(case_id, env["p1_headers"]), "ERR_CASE_NOT_SETUP_VERIFIED", 409
    )

    d3 = add_device(env, "d3", asset_tag="HLM-003")
    reconfigured = configure_pack(
        case_id, env["d2"]["id"], env["p1"]["id"], backup_device_id=d3["id"]
    )
    assert reconfigured["applied_preference_card_id"] == env["card"]["id"]
    cleared = read_case(case_id)
    assert cleared["bypass_status"] == "PACK_CONFIGURED"
    assert cleared["readiness_flag"] == "NONE", "a fresh pack configuration clears the flag"

    checklist = open_checklist(case_id, env["p1"]["id"], hematocrit_pct=26)
    verify_checklist(checklist["id"], env["p1"]["id"])
    assert read_case(case_id)["bypass_status"] == "SETUP_VERIFIED"

    on_pump = start_bypass(case_id, env["p1"]["id"])

    assert on_pump["bypass_status"] == "ON_BYPASS"
    assert on_pump["bypass_started_at"] is not None


def _lapsed_candidate_env(monthly_case_cap):
    """One hospital at `monthly_case_cap`, a lapsed candidate and an unstaffed second case."""
    env = {}
    env["contract"] = create_contract(monthly_case_cap=monthly_case_cap)
    env["surgeon"] = create_surgeon()
    env["card"] = create_preference_card(env["surgeon"]["id"])
    env["p1"] = create_perfusionist()
    env["p2"] = create_perfusionist(
        full_name="Tom Vasquez", employee_code="EMP-1003", career_case_count=90
    )
    env["chief"] = create_perfusionist(
        full_name="Nadia Oyelaran",
        employee_code="EMP-1002",
        is_chief=True,
        ecmo_privileged=None,
        career_case_count=200,
    )
    env["chief_headers"] = make_chief_perfusionist_headers(env["chief"]["id"])
    env["cert1"] = create_certification(env["p1"]["id"], expires_on="2026-08-02T00:00:00Z")
    create_ce_activity(env["p1"]["id"])
    create_certification(env["p2"]["id"])
    # 90 career cases give an experience ratio of 0.6, so this holder needs 30
    # counted credit hours to clear the 0.600 admission floor; a single claim may
    # carry at most 20, so the hours are claimed as two in-cycle activities.
    create_ce_activity(env["p2"]["id"], credit_hours=15, activity_date="2026-03-01T00:00:00Z")
    create_ce_activity(env["p2"]["id"], credit_hours=15, activity_date="2026-03-02T00:00:00Z")
    for holder in ("p1", "p2"):
        create_slot(
            env["contract"]["id"],
            env[holder]["id"],
            chief_id=env["chief"]["id"],
            window_end="2026-08-05T00:00:00Z",
        )
    case_a = create_case(
        env["contract"]["id"], env["surgeon"]["id"], chief_id=env["chief"]["id"]
    )
    env["case_a"] = assign_perfusionist(
        case_a["id"], env["p2"]["id"], case_a["version"], env["chief"]["id"]
    )
    env["case_b"] = create_case(
        env["contract"]["id"],
        env["surgeon"]["id"],
        chief_id=env["chief"]["id"],
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T12:00:00Z",
    )
    env["clock_report"] = set_clock("2026-08-02T00:00:00Z")
    return env


def _reissue_certification(perfusionist_id):
    """Give a lapsed perfusionist a current cycle with in-cycle credits."""
    create_certification(
        perfusionist_id, issued_on="2026-08-02T00:00:00Z", expires_on="2026-12-31T00:00:00Z"
    )
    create_ce_activity(perfusionist_id, activity_date="2026-08-02T00:00:00Z")


def _assign(env, case, perfusionist_id):
    """Attempt an assignment and hand back the raw response."""
    return api_client.assign_perfusionist(
        case["id"],
        build_assignment(perfusionist_id, case["version"]),
        env["chief_headers"],
    )


def test_the_credential_row_answers_before_the_case_cap_row_on_an_assignment():
    """A lapsed candidate at a hospital already on its cap reports the credential, then the cap.

    PRD 2.8: The service evaluates a fixed ladder of 72 ordered checks and returns the error of the **lowest-numbered** check that fails, stopping there.
    PRD 2.8: Rungs 41 through 54 are the clinical safety and compliance band, and their internal order encodes the group's central policy: credentialing outranks device readiness, device readiness outranks paperwork, and all of it outranks contract economics.
    PRD 2.8: Rung 72, evaluated last of all, is the fiscal capacity check: the contract's `accrued_case_count` remains below its `monthly_case_cap` when an assignment would take a fresh accrual slot, else `ERR_CONTRACT_CASE_CAP_EXCEEDED` (409).
    PRD 2.8: Its position at the bottom of the ladder is the concrete expression of the policy stated in §1: a perfusionist whose credentialing has lapsed and who is being assigned to a contract already at its cap reports the credentialing failure, because clinical rules are judged before commercial ones.

    Design: Difficulty/priority_pair_validation_conflict/cert_safety_beats_contract_case_cap_fiscal_on_assign
    """
    env = _lapsed_candidate_env(monthly_case_cap=1)
    assert env["clock_report"]["lapsed_certification_count"] == 1
    certs, _ = validate_paginated(
        api_client.list_certifications(env["p1"]["id"], ADMIN_HEADERS)
    )
    assert [row["status"] for row in certs] == ["LAPSED"]
    contract = read_contract(env["contract"]["id"])
    assert contract["accrued_case_count"] == 1
    assert contract["monthly_case_cap"] == 1

    cert_wins = _assign(env, env["case_b"], env["p1"]["id"])
    validate_error(cert_wins, "ERR_CERTIFICATION_NOT_CURRENT", 422)
    assert cert_wins.json()["data"]["error_id"] != "ERR_CONTRACT_CASE_CAP_EXCEEDED", (
        "the credential rung is judged above the fiscal capacity rung"
    )

    _reissue_certification(env["p1"]["id"])

    cap_wins = _assign(env, env["case_b"], env["p1"]["id"])
    validate_error(cap_wins, "ERR_CONTRACT_CASE_CAP_EXCEEDED", 409)
    assert_error_envelope(cap_wins, "ERR_CONTRACT_CASE_CAP_EXCEEDED")

    refused = read_case(env["case_b"]["id"])
    assert_case_dimensions(refused, "SCHEDULED", "UNBILLED")
    assert refused["assigned_perfusionist_id"] is None
    assert_contract_ledger(read_contract(env["contract"]["id"]), 400000, 1)


def test_with_the_cap_row_unarmed_the_credential_row_answers_alone_and_then_yields():
    """Below the cap only the credential can refuse, and a reissued cycle lets the case staff.

    PRD 2.8: Rungs 41 through 54 are the clinical safety and compliance band, and their internal order encodes the group's central policy: credentialing outranks device readiness, device readiness outranks paperwork, and all of it outranks contract economics.
    PRD 2.8: Rung 72, evaluated last of all, is the fiscal capacity check: the contract's `accrued_case_count` remains below its `monthly_case_cap` when an assignment would take a fresh accrual slot, else `ERR_CONTRACT_CASE_CAP_EXCEEDED` (409).
    PRD 3.4: The fiscal gate is last: the contract's `accrued_case_count` must be strictly below its `monthly_case_cap`, else `ERR_CONTRACT_CASE_CAP_EXCEEDED`.

    Design: Difficulty/priority_pair_validation_conflict/cert_safety_beats_contract_case_cap_fiscal_on_assign
    """
    env = _lapsed_candidate_env(monthly_case_cap=5)
    contract = read_contract(env["contract"]["id"])
    assert contract["accrued_case_count"] == 1
    assert contract["monthly_case_cap"] == 5

    cert_alone = _assign(env, env["case_b"], env["p1"]["id"])
    validate_error(cert_alone, "ERR_CERTIFICATION_NOT_CURRENT", 422)
    assert_case_dimensions(read_case(env["case_b"]["id"]), "SCHEDULED", "UNBILLED")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 400000, 1)

    _reissue_certification(env["p1"]["id"])

    staffed = validate_success(_assign(env, env["case_b"], env["p1"]["id"]))

    assert_case_dimensions(staffed, "STAFFED", "PROVISIONAL_ACCRUED")
    assert staffed["assigned_perfusionist_id"] == env["p1"]["id"]
    assert_cents(staffed["provisional_fee_cents"], 400000, "provisional_fee_cents")
    assert_cents(staffed["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 800000, 2)


def _two_staff_env():
    """One hospital, two credentialled perfusionists on primary call, no case yet."""
    env = base_setup(with_case=False)
    p2 = add_perfusionist(env, "p2", employee_code="EMP-1003", career_case_count=90)
    create_certification(p2["id"])
    # 90 career cases give an experience ratio of 0.6, so this holder needs 30
    # counted credit hours to clear the 0.600 admission floor; a single claim may
    # carry at most 20, so the hours are claimed as two in-cycle activities.
    create_ce_activity(p2["id"], credit_hours=15, activity_date="2026-03-01T00:00:00Z")
    create_ce_activity(p2["id"], credit_hours=15, activity_date="2026-03-02T00:00:00Z")
    add_slot(
        env,
        p2["id"],
        key="slot_p2",
        slot_type="PRIMARY_CALL",
        window_end="2026-08-05T00:00:00Z",
    )
    return env


def _run_and_close(env, perf_key, key, pump_minutes, **case_overrides):
    """Take one case from scheduling through the pump to closure."""
    perfusionist = env[perf_key]
    case = add_case(env, key=key, **case_overrides)
    case = assign_perfusionist(
        case["id"], perfusionist["id"], case["version"], env["chief"]["id"]
    )
    env[key] = case
    configure_pack(case["id"], env["d1"]["id"], perfusionist["id"])
    checklist = open_checklist(case["id"], perfusionist["id"], hematocrit_pct=26)
    verify_checklist(checklist["id"], perfusionist["id"])
    start_bypass(case["id"], perfusionist["id"])
    end_bypass(
        case["id"],
        perfusionist["id"],
        pump_time_minutes=pump_minutes,
        cross_clamp_minutes=80,
        lowest_hematocrit_pct=25,
        adverse_event_count=0,
    )
    return close_case(case["id"], env["chief"]["id"])


def test_the_prolonged_surcharge_starts_at_exactly_the_threshold_minute():
    """179 reported minutes buy no surcharge unit and 180 buy the first one.

    PRD 3.4: The final variant, run at case close, takes its minutes from the case's reported `pump_time_minutes`.
    PRD 3.4: If the minute figure is strictly below the contract's `prolonged_pump_threshold_minutes`, no prolonged-perfusion units accrue.
    PRD 3.4: Otherwise the number of units is the whole-number result, rounded down, of the excess minutes over that threshold divided by 30 — one unit per half hour of prolonged perfusion — plus one.
    PRD 3.4: The boundary is inclusive on purpose: a case whose minutes exactly equal the threshold earns one unit, and a case one minute short of it earns none.
    PRD 3.4: The surcharge fraction is the number of units multiplied by the contract's `prolonged_surcharge_pct`.
    PRD 3.4: The fee in cents is then the contract's `per_case_fee_cents` multiplied by one plus the acuity fraction plus the surcharge fraction, rounded half up to a whole number of cents exactly once, at the end, on the fully multiplied product — never term by term.

    Design: Difficulty/boundary_precision_check/prolonged_surcharge_triggers_at_exactly_threshold_minutes
    """
    env = _two_staff_env()
    assert env["contract"]["prolonged_pump_threshold_minutes"] == 180

    below = _run_and_close(env, "p1", "case_below", 179)
    assert_cents(env["case_below"]["provisional_fee_cents"], 400000, "provisional_fee_cents")
    assert_cents(below["final_fee_cents"], 400000, "final_fee_cents")

    at_threshold = _run_and_close(
        env,
        "p2",
        "case_at",
        180,
        scheduled_start="2026-08-02T14:00:00Z",
        scheduled_end="2026-08-02T20:00:00Z",
    )

    # 400000 * (1 + 1 * 0.15) is exactly 460000: one unit at the inclusive boundary.
    assert_cents(at_threshold["final_fee_cents"], 460000, "final_fee_cents")
    assert at_threshold["final_fee_cents"] - below["final_fee_cents"] == 60000, (
        "the single minute at the boundary costs fifteen percent of the base fee"
    )
    assert_contract_ledger(read_contract(env["contract"]["id"]), 860000, 2)
    assert read_perfusionist(env["p1"]["id"])["career_case_count"] == 151
    assert read_perfusionist(env["p2"]["id"])["career_case_count"] == 91


def test_the_second_surcharge_unit_waits_for_a_full_half_hour_past_the_threshold():
    """29 excess minutes still buy one unit, and the thirtieth buys the second.

    PRD 3.4: If the minute figure is strictly below the contract's `prolonged_pump_threshold_minutes`, no prolonged-perfusion units accrue.
    PRD 3.4: Otherwise the number of units is the whole-number result, rounded down, of the excess minutes over that threshold divided by 30 — one unit per half hour of prolonged perfusion — plus one.
    PRD 3.4: The surcharge fraction is the number of units multiplied by the contract's `prolonged_surcharge_pct`.
    PRD 3.4: The fee in cents is then the contract's `per_case_fee_cents` multiplied by one plus the acuity fraction plus the surcharge fraction, rounded half up to a whole number of cents exactly once, at the end, on the fully multiplied product — never term by term.

    Design: Difficulty/boundary_precision_check/prolonged_surcharge_triggers_at_exactly_threshold_minutes
    """
    env = _two_staff_env()

    one_unit = _run_and_close(env, "p1", "case_one_unit", 209)
    # FLOOR(29 / 30) is 0, and the rule adds one unit on top of that.
    assert_cents(one_unit["final_fee_cents"], 460000, "final_fee_cents")

    two_units = _run_and_close(
        env,
        "p2",
        "case_two_units",
        210,
        scheduled_start="2026-08-02T14:00:00Z",
        scheduled_end="2026-08-02T20:00:00Z",
    )

    # FLOOR(30 / 30) is 1, so the fee carries two units of 0.15.
    assert_cents(two_units["final_fee_cents"], 520000, "final_fee_cents")
    assert two_units["final_fee_cents"] - one_unit["final_fee_cents"] == 60000
    assert_contract_ledger(read_contract(env["contract"]["id"]), 980000, 2)


def test_a_primary_with_no_designated_standby_is_refused_however_full_the_fleet_is():
    """Zero resolvable standbys refuses the pack, and naming one takes the set to exactly one.

    PRD 3.5: The standby machine is resolved rather than simply supplied.
    PRD 3.5: If the request carries `backup_device_id`, that is the standby; otherwise the standby is the machine designated as the primary's own `backup_device_id`.
    PRD 3.5: If neither source yields a machine, the request is refused with `ERR_NO_BACKUP_DEVICE_AVAILABLE` — the group does not go on pump without a second pump in the room.
    PRD 3.5: Both machines end at `RESERVED`: a machine that was `AVAILABLE` moves `AVAILABLE → RESERVED`, and a machine already `RESERVED` for another non-colliding case simply stays `RESERVED` with a higher reservation count.
    PRD 3.5: A pack whose `substitutions` array is non-empty has `requires_surgeon_approval` set true and `approval_status` set to `PENDING`; a pack with no substitutions has `requires_surgeon_approval` false and `approval_status` `NOT_REQUIRED`, and needs no further human act.

    Design: Difficulty/boundary_precision_check/pack_config_rejects_when_backup_device_pool_is_empty
    """
    env = staffed_setup()
    solo = add_device(env, "d_solo", asset_tag="HLM-SOLO")
    assert solo["backup_device_id"] is None
    assert_device_state(read_device(env["d2"]["id"]), "AVAILABLE", open_reservation_count=0)

    empty_pool = api_client.configure_disposable_pack(
        env["case"]["id"],
        build_pack_configuration(solo["id"]),
        make_perfusionist_headers(env["p1"]["id"]),
    )
    validate_error(empty_pool, "ERR_NO_BACKUP_DEVICE_AVAILABLE", 422)
    assert_error_envelope(empty_pool, "ERR_NO_BACKUP_DEVICE_AVAILABLE")
    refused_case = read_case(env["case"]["id"])
    assert refused_case["bypass_status"] == "STAFFED"
    assert refused_case["primary_device_id"] is None
    assert_device_state(read_device(solo["id"]), "AVAILABLE", open_reservation_count=0)

    pack = configure_pack(
        env["case"]["id"], solo["id"], env["p1"]["id"], backup_device_id=env["d2"]["id"]
    )

    configured = read_case(env["case"]["id"])
    assert configured["bypass_status"] == "PACK_CONFIGURED"
    assert configured["primary_device_id"] == solo["id"]
    assert configured["backup_device_id"] == env["d2"]["id"]
    assert_device_state(read_device(solo["id"]), "RESERVED", open_reservation_count=1)
    assert_device_state(read_device(env["d2"]["id"]), "RESERVED", open_reservation_count=1)
    assert_cents(pack["pack_cost_cents"], 3741, "pack_cost_cents")
    assert pack["approval_status"] == "NOT_REQUIRED"
    assert pack["requires_surgeon_approval"] is False


def test_commissioning_a_second_machine_is_what_crosses_the_empty_standby_boundary():
    """With one machine in the fleet the pack is refused; the second machine admits it.

    PRD 3.5: If the request carries `backup_device_id`, that is the standby; otherwise the standby is the machine designated as the primary's own `backup_device_id`.
    PRD 3.5: If neither source yields a machine, the request is refused with `ERR_NO_BACKUP_DEVICE_AVAILABLE` — the group does not go on pump without a second pump in the room.
    PRD 3.5: The resolved standby must exist, must be a `HEART_LUNG_MACHINE` at the case's hospital, must be `AVAILABLE` or `RESERVED`, and must not be the primary machine itself; a standby that is the same row as the primary, or of a different class, or stationed at a different hospital, is `ERR_INVALID_BACKUP_DEVICE`.
    PRD 3.5: Both machines end at `RESERVED`: a machine that was `AVAILABLE` moves `AVAILABLE → RESERVED`, and a machine already `RESERVED` for another non-colliding case simply stays `RESERVED` with a higher reservation count.

    Design: Difficulty/boundary_precision_check/pack_config_rejects_when_backup_device_pool_is_empty
    """
    env = staffed_setup(with_devices=False)
    solo = add_device(env, "d_solo", asset_tag="HLM-SOLO")

    refused = api_client.configure_disposable_pack(
        env["case"]["id"],
        build_pack_configuration(solo["id"]),
        make_perfusionist_headers(env["p1"]["id"]),
    )
    validate_error(refused, "ERR_NO_BACKUP_DEVICE_AVAILABLE", 422)
    assert read_case(env["case"]["id"])["bypass_status"] == "STAFFED"
    assert_device_state(read_device(solo["id"]), "AVAILABLE", open_reservation_count=0)

    spare = add_device(env, "d3", asset_tag="HLM-003")
    pack = configure_pack(
        env["case"]["id"], solo["id"], env["p1"]["id"], backup_device_id=spare["id"]
    )

    assert pack["applied_preference_card_id"] == env["card"]["id"]
    configured = read_case(env["case"]["id"])
    assert configured["bypass_status"] == "PACK_CONFIGURED"
    assert configured["primary_device_id"] == solo["id"]
    assert configured["backup_device_id"] == spare["id"]
    assert_device_state(read_device(solo["id"]), "RESERVED", open_reservation_count=1)
    assert_device_state(read_device(spare["id"]), "RESERVED", open_reservation_count=1)
