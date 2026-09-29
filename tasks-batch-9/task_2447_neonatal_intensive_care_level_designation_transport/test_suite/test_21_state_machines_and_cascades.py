"""Non-linear state machines and multi-link cascades.

Covers the cyclic, bounded information-request loop on a referral (PRD §3.3), the
two independent state dimensions an admission carries (PRD §3.7), the mode fork
and its join point on a transport run (PRD §3.6), the capability cascade that an
out-of-service asset sets off (PRD §3.8), and the chain that a back-transfer
admission runs at the *source* unit — completing the referral, transferring the
source admission, freeing its bed and draining its deferral queue (PRD §3.4,
§3.7, §3.8).
"""

from datetime import datetime
from typing import Any, Dict, Tuple

from test_helpers import (
    CLOCK_START,
    assert_close,
    assert_unit_counts,
    factories,
    fixtures,
    get_success_data,
    validate_success,
)

# ---------------------------------------------------------------------------
# Local conveniences
# ---------------------------------------------------------------------------


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _same_instant(actual: str, expected: str) -> bool:
    """Server-stamped instants carry three fractional digits, so compare the
    instants themselves rather than their rendering."""
    assert actual is not None
    return _instant(actual) == _instant(expected)


# ---------------------------------------------------------------------------
# PRD §3.3 — the bounded information-request cycle on a referral
# ---------------------------------------------------------------------------


def _referral_awaiting_information(api) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A PENDING inbound case at the regional unit: 34.0 weeks, 2000 g, room air,
    which asks for LEVEL_II on its anticipated need alone."""
    env = fixtures.setup_network()
    referral = fixtures.create_referral(
        env,
        case_reference="CASE-L1",
        gestational_age_weeks=34.0,
        birth_weight_grams=2000,
        support_modality="ROOM_AIR",
    )
    return env, referral


def test_information_request_loop_runs_twice_and_recomputes_the_level(api):
    """PRD §3.3: "Where the receiving unit needs more data before deciding, its `IntakeNeonatologist` asks for it, moving the referral `PENDING → INFO_REQUESTED` or `DEFERRED → INFO_REQUESTED` and recording the free-text `requested_items` it wants."

    PRD §3.3: "The referring side answers by supplying any of `support_modality`, `birth_weight_grams`, `gestational_age_weeks`, `diagnoses` and `planned_surgery`, each optional, which moves the referral `INFO_REQUESTED → PENDING`, increments `info_request_rounds` by one, clears `requested_items` back to null, applies the supplied clinical values, and then recomputes `required_level`, `level_basis`, `maternal_transfer_preferred` and `triage_priority` from the revised inputs — so an answer can raise or lower the level the case demands."

    Design: Difficulty/non_linear_state_machine/referral_info_request_cycle_bounded_at_two_rounds
    """
    env, referral = _referral_awaiting_information(api)
    referral_id = referral["id"]

    # First entry into the loop: the request alone does not complete a round.
    asked = validate_success(
        api.request_referral_info(
            referral_id,
            factories.request_info_payload("cord gas, antenatal steroid course"),
            env["intake_a"],
        )
    )
    assert asked["status"] == "INFO_REQUESTED"
    assert asked["info_request_rounds"] == 0

    # The answer closes the round, clears the ask and returns the case to PENDING.
    answered = validate_success(
        api.provide_referral_info(
            referral_id,
            factories.provide_info_payload(gestational_age_weeks=34.0),
            env["ref_b"],
        )
    )
    assert answered["status"] == "PENDING"
    assert answered["info_request_rounds"] == 1
    assert answered["requested_items"] is None

    # Second entry is still permitted, because one round is strictly below two.
    asked_again = validate_success(
        api.request_referral_info(
            referral_id,
            factories.request_info_payload("current respiratory support"),
            env["intake_a"],
        )
    )
    assert asked_again["status"] == "INFO_REQUESTED"
    assert asked_again["info_request_rounds"] == 1

    # The second answer raises the level the case demands: conventional ventilation
    # makes the current support term LEVEL_III, which the anticipated variant only
    # equals, so the basis falls back to CURRENT_SUPPORT.
    answered_again = validate_success(
        api.provide_referral_info(
            referral_id,
            factories.provide_info_payload(support_modality="CONVENTIONAL_VENT"),
            env["ref_b"],
        )
    )
    assert answered_again["status"] == "PENDING"
    assert answered_again["info_request_rounds"] == 2
    assert answered_again["required_level"] == "LEVEL_III"
    assert answered_again["level_basis"] == "CURRENT_SUPPORT"
    assert_close(answered_again["triage_priority"], 55.00)


def test_third_information_request_diverts_instead_of_re_entering_the_loop(api):
    """PRD §3.3: "This loop is bounded at two completed rounds: the request is only permitted while `info_request_rounds` is strictly below 2, and a request made when `info_request_rounds` already equals 2 does not enter `INFO_REQUESTED` at all — it moves the referral to `DIVERTED` with `decision_reason` `INFO_ROUNDS_EXHAUSTED`."

    PRD §3.3: "`DECLINED`, `DIVERTED`, `WITHDRAWN`, `REVOKED`, `SUPERSEDED` and `COMPLETED` are all terminal statuses for a referral."

    Design: Difficulty/non_linear_state_machine/referral_info_request_cycle_bounded_at_two_rounds
    """
    env, referral = _referral_awaiting_information(api)
    referral_id = referral["id"]

    # Walk the two permitted rounds through the documented endpoints.
    for items, answer in (
        ("cord gas, antenatal steroid course", {"gestational_age_weeks": 34.0}),
        ("current respiratory support", {"support_modality": "CONVENTIONAL_VENT"}),
    ):
        get_success_data(
            api.request_referral_info(
                referral_id, factories.request_info_payload(items), env["intake_a"]
            )
        )
        get_success_data(
            api.provide_referral_info(
                referral_id, factories.provide_info_payload(**answer), env["ref_b"]
            )
        )

    diverted = validate_success(
        api.request_referral_info(
            referral_id, factories.request_info_payload("blood gas trend"), env["intake_a"]
        )
    )
    assert diverted["status"] == "DIVERTED"
    assert diverted["decision_reason"] == "INFO_ROUNDS_EXHAUSTED"
    assert diverted["info_request_rounds"] == 2


# ---------------------------------------------------------------------------
# PRD §3.7 — the two independent dimensions of an admission
# ---------------------------------------------------------------------------


def _admitted_infant(api) -> Tuple[Dict[str, Any], str]:
    """One ADMITTED infant at the regional unit from a 29.0-week, 1200 g case."""
    env = fixtures.setup_network()
    admission = fixtures.admit_case(
        env,
        case_reference="CASE-P1",
        gestational_age_weeks=29.0,
        birth_weight_grams=1200,
        support_modality="ROOM_AIR",
    )
    return env, admission["id"]


def _walk_to_back_transfer_ready(env, api, admission_id: str) -> Dict[str, Any]:
    """A day of care in room air with a central line, two developmental rounds and
    a surveillance suspicion, then the readiness attestation."""
    get_success_data(
        api.create_care_update(
            admission_id,
            factories.care_update_payload(
                current_weight_grams=1900,
                support_modality="ROOM_AIR",
                central_line_present=True,
                ventilated=False,
            ),
            env["nurse"],
        )
    )
    get_success_data(
        api.create_infection_event(
            admission_id, factories.infection_event_payload("SUSPECT"), env["nurse"]
        )
    )
    fixtures.developmental_rounds(
        env,
        admission_id,
        count=2,
        kangaroo_care_minutes=60,
        family_presence_minutes=240,
        cluster_care_compliant=True,
        light_cycling_compliant=False,
    )
    return fixtures.attest_back_transfer_ready(
        env,
        admission_id,
        back_transfer_attestation_note=(
            "Room air, gaining, line still in situ under surveillance"
        ),
    )


def test_care_dimension_walks_to_back_transfer_ready_leaving_surveillance_alone(api):
    """PRD §3.7: "Any value of one dimension may coexist with any value of the other, and a transition on one dimension never moves the other."

    PRD §3.7: "One care-status consequence rides along: when the posted `support_modality` is `ROOM_AIR` or `CPAP` and the admission is in `ADMITTED`, the posting moves it `ADMITTED → STABILIZED`."

    PRD §3.7: "`SUSPECT` moves the admission `SURVEILLANCE_CLEAR → SUSPECTED` or `RESOLVED → SUSPECTED`, and quarantines the infant's feed: every milk batch for that admission whose status is `RECEIVED`, `VERIFIED` or `PARTIALLY_ADMINISTERED` is moved to `QUARANTINED`, with its previous status preserved in `pre_quarantine_status`."

    Design: Difficulty/non_linear_state_machine/admission_care_and_infection_dimensions_advance_independently
    """
    env, admission_id = _admitted_infant(api)

    # A day of care moves only the care dimension; 1900 g in room air makes both
    # the weight and the support term LEVEL_I.
    cared = validate_success(
        api.create_care_update(
            admission_id,
            factories.care_update_payload(
                current_weight_grams=1900,
                support_modality="ROOM_AIR",
                central_line_present=True,
                ventilated=False,
            ),
            env["nurse"],
        )
    )
    assert cared["care_status"] == "STABILIZED"
    assert cared["infection_status"] == "SURVEILLANCE_CLEAR"
    assert cared["central_line_days"] == 1
    assert cared["current_care_level"] == "LEVEL_I"

    # A surveillance suspicion moves only the infection dimension.
    suspected = validate_success(
        api.create_infection_event(
            admission_id, factories.infection_event_payload("SUSPECT"), env["nurse"]
        )
    )
    assert suspected["care_status"] == "STABILIZED"
    assert suspected["infection_status"] == "SUSPECTED"

    # Readiness is attested on the care dimension while the suspicion still stands.
    fixtures.developmental_rounds(
        env,
        admission_id,
        count=2,
        kangaroo_care_minutes=60,
        family_presence_minutes=240,
        cluster_care_compliant=True,
        light_cycling_compliant=False,
    )
    ready = validate_success(
        api.attest_back_transfer_ready(
            admission_id,
            factories.back_transfer_ready_payload(
                "Room air, gaining, line still in situ under surveillance"
            ),
            env["intake_a"],
        )
    )
    assert ready["care_status"] == "BACK_TRANSFER_READY"
    assert ready["infection_status"] == "SUSPECTED"
    assert_close(ready["developmental_bundle_score"], 60.00)


def test_infection_dimension_recycles_without_touching_the_care_dimension(api):
    """PRD §3.7: "`CONFIRM_CLABSI` moves the admission `SUSPECTED → CONFIRMED_CLABSI` and requires `central_line_days` to be at least 1 — a central-line-associated infection is definitionally impossible without a line day on the record — and stamps `infection_confirmed_at` with the current clock instant, which is the timestamp surveillance periods filter on."

    PRD §3.7: "`RESOLVE` moves the admission `SUSPECTED → RESOLVED` or `CONFIRMED_CLABSI → RESOLVED` and replays the quarantine: every `QUARANTINED` batch returns to the status recorded in its `pre_quarantine_status`, and `pre_quarantine_status` is then cleared back to null."

    PRD §3.7: "Any value of one dimension may coexist with any value of the other, and a transition on one dimension never moves the other."

    Design: Difficulty/non_linear_state_machine/admission_care_and_infection_dimensions_advance_independently
    """
    env, admission_id = _admitted_infant(api)
    _walk_to_back_transfer_ready(env, api, admission_id)

    confirmed = validate_success(
        api.create_infection_event(
            admission_id, factories.infection_event_payload("CONFIRM_CLABSI"), env["nurse"]
        )
    )
    assert confirmed["care_status"] == "BACK_TRANSFER_READY"
    assert confirmed["infection_status"] == "CONFIRMED_CLABSI"
    assert _same_instant(confirmed["infection_confirmed_at"], CLOCK_START)

    resolved = validate_success(
        api.create_infection_event(
            admission_id, factories.infection_event_payload("RESOLVE"), env["nurse"]
        )
    )
    assert resolved["care_status"] == "BACK_TRANSFER_READY"
    assert resolved["infection_status"] == "RESOLVED"

    # The infection dimension carries no round bound: RESOLVED re-enters SUSPECTED.
    suspected_again = validate_success(
        api.create_infection_event(
            admission_id, factories.infection_event_payload("SUSPECT"), env["nurse"]
        )
    )
    assert suspected_again["care_status"] == "BACK_TRANSFER_READY"
    assert suspected_again["infection_status"] == "SUSPECTED"


# ---------------------------------------------------------------------------
# PRD §3.6 — the dispatch fork and its join point
# ---------------------------------------------------------------------------

GROUND_DEPART_AT = "2026-08-02T08:00:00Z"
GROUND_RETURN_AT = "2026-08-02T12:00:00Z"
GROUND_ISOLETTE_FREE_AT = "2026-08-02T12:45:00Z"
AIR_DEPART_AT = "2026-08-02T14:00:00Z"
AIR_RETURN_AT = "2026-08-02T18:00:00Z"
AIR_ISOLETTE_FREE_AT = "2026-08-02T19:30:00Z"


def _two_activated_runs_on_one_isolette(api) -> Tuple[Dict[str, Any], str, str, str]:
    """Two accepted LEVEL_III cases at the regional unit, then two ACTIVATED runs
    on the same isolette over disjoint occupation intervals: a ground run and a
    rotor-wing run."""
    env = fixtures.setup_network(with_isolette=True)
    isolette_id = env["assets"]["TRANSPORT_ISOLETTE"]["id"]

    _, first = fixtures.hold_bed(
        env,
        case_reference="CASE-F1",
        gestational_age_weeks=30.0,
        birth_weight_grams=1250,
        support_modality="HFOV",
    )
    _, second = fixtures.hold_bed(
        env,
        case_reference="CASE-F2",
        gestational_age_weeks=30.0,
        birth_weight_grams=1250,
        support_modality="HFOV",
    )

    ground_run = fixtures.create_run(
        env,
        first["reservation_id"],
        mode="GROUND",
        crew_composition=["TRANSPORT_RN", "NNP"],
        depart_at=GROUND_DEPART_AT,
        planned_return_at=GROUND_RETURN_AT,
        weather_minimums_met=False,
    )
    air_run = fixtures.create_run(
        env,
        second["reservation_id"],
        mode="ROTOR_WING",
        crew_composition=["TRANSPORT_RN", "RT_NEO"],
        depart_at=AIR_DEPART_AT,
        planned_return_at=AIR_RETURN_AT,
        weather_minimums_met=True,
    )
    return env, isolette_id, ground_run["id"], air_run["id"]


def test_ground_dispatch_takes_the_forty_five_minute_branch(api):
    """PRD §3.6: "A ground dispatch moves the run `ACTIVATED → GROUND_ROLLING`; it requires `mode` to be `GROUND`, requires `crew_composition` to contain `TRANSPORT_RN`, and requires the assigned isolette's derived `status` to be `IN_SERVICE`; it then sets that isolette's `decontamination_ready_at` to `planned_return_at` advanced by 45 minutes."

    PRD §3.6: "Its `decontamination_minutes` is derived from the mode: 45 minutes for a `GROUND` run, and 90 minutes — an hour and a half — for both `ROTOR_WING` and `FIXED_WING`, because an aircraft cabin takes longer to turn round than an ambulance."

    Design: Difficulty/non_linear_state_machine/transport_run_mode_fork_joins_at_on_scene
    """
    env, isolette_id, ground_run_id, _ = _two_activated_runs_on_one_isolette(api)

    # Weather minimums were attested false, which the ground branch never reads.
    dispatched = validate_success(api.dispatch_transport_run(ground_run_id, {}, env["coord"]))
    assert dispatched["status"] == "GROUND_ROLLING"
    assert dispatched["decontamination_minutes"] == 45
    assert dispatched["weather_minimums_met"] is False

    asset = validate_success(api.get_equipment_asset(isolette_id, env["admin"]))
    assert _same_instant(asset["decontamination_ready_at"], GROUND_ISOLETTE_FREE_AT)


def test_air_dispatch_takes_the_ninety_minute_branch_and_both_join_at_on_scene(api):
    """PRD §3.6: "An air dispatch moves the run `ACTIVATED → AIR_LAUNCHED`; it requires `mode` to be either `ROTOR_WING` or `FIXED_WING`, requires `weather_minimums_met` to be true, requires `crew_composition` to contain `TRANSPORT_RN`, and requires the isolette's derived `status` to be `IN_SERVICE`; it then sets that isolette's `decontamination_ready_at` to `planned_return_at` advanced by 90 minutes."

    PRD §3.6: "Both branches join at the referring hospital: arriving on scene moves the run `GROUND_ROLLING → ON_SCENE` or `AIR_LAUNCHED → ON_SCENE` and has no side effects of its own."

    Design: Difficulty/non_linear_state_machine/transport_run_mode_fork_joins_at_on_scene
    """
    env, isolette_id, ground_run_id, air_run_id = _two_activated_runs_on_one_isolette(api)
    fixtures.dispatch_run(env, ground_run_id)

    launched = validate_success(api.dispatch_transport_run(air_run_id, {}, env["coord"]))
    assert launched["status"] == "AIR_LAUNCHED"
    assert launched["decontamination_minutes"] == 90

    asset = validate_success(api.get_equipment_asset(isolette_id, env["admin"]))
    assert _same_instant(asset["decontamination_ready_at"], AIR_ISOLETTE_FREE_AT)

    # One trigger name, one target state, whichever branch the run came down.
    from_ground = validate_success(api.transport_run_on_scene(ground_run_id, {}, env["coord"]))
    from_air = validate_success(api.transport_run_on_scene(air_run_id, {}, env["coord"]))
    assert from_ground["status"] == "ON_SCENE"
    assert from_air["status"] == "ON_SCENE"


# ---------------------------------------------------------------------------
# PRD §3.8 — the capability cascade
# ---------------------------------------------------------------------------


def _unit_with_a_held_run_and_a_level_three_infant(api) -> Dict[str, Any]:
    """The regional unit at LEVEL_III with one occupied bed carrying a LEVEL_III
    infant, one held bed for a second LEVEL_III case, and an ACTIVATED ground run
    standing on that hold."""
    env = fixtures.setup_network(with_isolette=True)

    settled = fixtures.create_referral(
        env,
        case_reference="CASE-E1",
        gestational_age_weeks=29.0,
        birth_weight_grams=1200,
        support_modality="ROOM_AIR",
    )
    fixtures.accept_referral(env, settled["id"])
    admission = fixtures.admit(env, settled["id"])

    in_flight, accepted = fixtures.hold_bed(
        env,
        case_reference="CASE-E2",
        gestational_age_weeks=30.0,
        birth_weight_grams=1250,
        support_modality="HFOV",
    )
    run = fixtures.create_run(
        env,
        accepted["reservation_id"],
        mode="GROUND",
        crew_composition=["TRANSPORT_RN", "NNP"],
        depart_at=GROUND_DEPART_AT,
        planned_return_at=GROUND_RETURN_AT,
        weather_minimums_met=False,
    )

    env["case_settled"] = settled
    env["case_in_flight"] = in_flight
    env["reservation_in_flight"] = accepted["reservation_id"]
    env["run_in_flight"] = run["id"]
    env["admission_settled"] = admission["id"]
    return env


def test_out_of_service_asset_cascades_through_the_unit_level_to_the_run_abort(api):
    """PRD §3.8: "In one operation, the asset's `out_of_service_at` is stamped at the current clock instant, making its derived `status` `OUT_OF_SERVICE`; the unit's `equipment_compliant`, `capability_level` and `effective_level` are re-derived; a `designation_status` of `PROVISIONAL` or `DESIGNATED` becomes `CONDITIONAL` when the asset was required for the unit's `designated_level`; every referral at that unit whose status is `PENDING`, `INFO_REQUESTED`, `DEFERRED` or `ACCEPTED` and whose `required_level` now outranks the new `effective_level` is moved to `DIVERTED` with `decision_reason` `CAPABILITY_LOST`, with its `HELD` reservation moved to `RELEASED` with `released_reason` `CAPABILITY_LOST` and any non-terminal transport run against that reservation moved to `ABORTED` with `abort_reason` `CAPABILITY_LOST`; every admission at that unit whose `care_status` is `ADMITTED` or `STABILIZED` and whose `current_care_level` now outranks the new `effective_level` is moved to `BACK_TRANSFER_REQUIRED`; and the unit's `version` advances by one."

    PRD §2.7: "`effective_level` is the lower-ranking of `designated_level` and `capability_level`, and it — not the designated level — gates every referral acceptance."

    Design: Difficulty/transitive_cascade/equipment_out_of_service_cascades_to_transport_abort
    """
    env = _unit_with_a_held_run_and_a_level_three_infant(api)

    # Link 1: the high-frequency oscillator is the asset the LEVEL_III standard needs.
    asset = validate_success(
        api.take_equipment_asset_out_of_service(
            env["assets"]["HFOV"]["id"],
            factories.out_of_service_payload("BIOMED_FAULT"),
            env["dir_a"],
        )
    )
    assert asset["status"] == "OUT_OF_SERVICE"
    assert _same_instant(asset["out_of_service_at"], CLOCK_START)

    # Link 2: the unit can no longer prove LEVEL_III, so it falls back to LEVEL_II.
    unit = fixtures.read_unit(env)
    assert unit["equipment_compliant"] is False
    assert unit["capability_level"] == "LEVEL_II"
    assert unit["effective_level"] == "LEVEL_II"
    assert unit["designation_status"] == "CONDITIONAL"

    # Link 3: the accepted LEVEL_III case now outranks the unit, so it is diverted
    # and its hold released.
    diverted = fixtures.read_referral(env, env["case_in_flight"]["id"])
    assert diverted["status"] == "DIVERTED"
    assert diverted["decision_reason"] == "CAPABILITY_LOST"

    reservation = fixtures.read_reservation(env, env["reservation_in_flight"])
    assert reservation["status"] == "RELEASED"
    assert reservation["released_reason"] == "CAPABILITY_LOST"

    # Link 4: the crew already activated against that hold is stood down.
    run = validate_success(api.get_transport_run(env["run_in_flight"], env["coord"]))
    assert run["status"] == "ABORTED"
    assert run["abort_reason"] == "CAPABILITY_LOST"


def test_capability_loss_requires_back_transfer_and_spares_terminal_referrals(api):
    """PRD §3.8: "When a unit loses capability and an admitted infant's `current_care_level` now outranks the unit's new `effective_level`, the admission is moved `ADMITTED → BACK_TRANSFER_REQUIRED` or `STABILIZED → BACK_TRANSFER_REQUIRED` by the cascade described below."

    PRD §2.8: "Its `occupied_bed_count` is the number of the unit's admissions whose `care_status` is one of `ADMITTED`, `STABILIZED`, `BACK_TRANSFER_READY` or `BACK_TRANSFER_REQUIRED`."

    PRD §2.8: "And `available_bed_count` is the base staffed bed target plus the escalation bed count, minus the occupied bed count, minus the held bed count."

    Design: Difficulty/transitive_cascade/equipment_out_of_service_cascades_to_transport_abort
    """
    env = _unit_with_a_held_run_and_a_level_three_infant(api)

    validate_success(
        api.take_equipment_asset_out_of_service(
            env["assets"]["HFOV"]["id"],
            factories.out_of_service_payload("BIOMED_FAULT"),
            env["dir_a"],
        )
    )

    # The 1200 g infant sits at LEVEL_III, which the LEVEL_II unit can no longer hold.
    admission = fixtures.read_admission(env, env["admission_settled"])
    assert admission["current_care_level"] == "LEVEL_III"
    assert admission["care_status"] == "BACK_TRANSFER_REQUIRED"

    # A required back-transfer still occupies its bed; the released hold does not.
    unit = fixtures.read_unit(env)
    assert_unit_counts(unit, occupied=1, held=0, available=3)

    # The referral that already completed into an admission is terminal and untouched.
    settled = fixtures.read_referral(env, env["case_settled"]["id"])
    assert settled["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# PRD §3.8 — a back-transfer admission drains the source unit's queue
# ---------------------------------------------------------------------------


def _back_transfer_accepted_with_a_deferred_case_behind_it(api) -> Dict[str, Any]:
    """The regional unit holds one staffed bed, filled by a BACK_TRANSFER_READY
    infant; its onward referral is already accepted at the community hospital, and
    a LEVEL_II case sits DEFERRED in the regional unit's queue."""
    env = fixtures.setup_network()

    source = fixtures.admit_case(
        env,
        case_reference="CASE-T1",
        gestational_age_weeks=29.0,
        birth_weight_grams=1200,
        support_modality="ROOM_AIR",
    )
    source_id = source["id"]
    fixtures.care_update(
        env,
        source_id,
        current_weight_grams=1900,
        support_modality="ROOM_AIR",
        central_line_present=False,
        ventilated=False,
    )
    fixtures.developmental_rounds(
        env,
        source_id,
        count=2,
        kangaroo_care_minutes=60,
        family_presence_minutes=240,
        cluster_care_compliant=True,
        light_cycling_compliant=False,
    )
    fixtures.attest_back_transfer_ready(
        env,
        source_id,
        back_transfer_attestation_note="1900 g, room air, full feeds — community level appropriate",
    )

    # Shrink the regional unit to its single occupied bed so nothing is free.
    fixtures.patch_unit(env, staffed_bed_target=1)

    onward = fixtures.back_transfer_referral(
        env, source_id, receiving_unit_id=env["unit_b_id"], case_reference="BT-1"
    )
    accepted = fixtures.accept_referral(env, onward["id"], unit_id=env["unit_b_id"])

    waiting = fixtures.create_referral(
        env,
        case_reference="CASE-T2",
        gestational_age_weeks=34.0,
        birth_weight_grams=1600,
        support_modality="ROOM_AIR",
    )
    get_success_data(api.defer_referral(waiting["id"], {}, env["intake_a"]))

    env["source_admission"] = source_id
    env["onward_referral"] = onward["id"]
    env["onward_reservation"] = accepted["reservation_id"]
    env["waiting_referral"] = waiting["id"]
    return env


def test_back_transfer_admission_completes_the_referral_and_transfers_the_source(api):
    """PRD §3.7: "The referral is moved `ACCEPTED → COMPLETED` and its `HELD` reservation to `OCCUPIED` with `released_reason` `ADMITTED`; the bed has not been freed, it has changed category, and the ledger invariant of §2.8 holds throughout."

    PRD §3.8: "When the community hospital admits against a `BACK_TRANSFER` referral, the new admission's `back_transfer_source_admission_id` is set to the regional-centre admission it continues, and that source admission is moved `BACK_TRANSFER_READY → TRANSFERRED` or `BACK_TRANSFER_REQUIRED → TRANSFERRED` with `discharged_at` stamped at the current clock instant and `discharge_disposition` set to `BACK_TRANSFERRED`."

    Design: Difficulty/transitive_cascade/back_transfer_admission_cascades_to_queue_promotion
    """
    env = _back_transfer_accepted_with_a_deferred_case_behind_it(api)

    # Link 1: the community hospital admits the graduate against its own hold.
    admission = validate_success(
        api.create_admission(
            factories.admission_payload(env["onward_referral"]), env["intake_b"]
        ),
        201,
    )
    assert admission["unit_id"] == env["unit_b_id"]
    assert admission["care_status"] == "ADMITTED"
    assert admission["back_transfer_source_admission_id"] == env["source_admission"]

    # Link 2: the onward referral closes and its hold changes category.
    onward = fixtures.read_referral(env, env["onward_referral"])
    assert onward["status"] == "COMPLETED"

    reservation = fixtures.read_reservation(env, env["onward_reservation"])
    assert reservation["status"] == "OCCUPIED"
    assert reservation["released_reason"] == "ADMITTED"

    # Link 3: the regional-centre admission it continues is transferred out.
    source = fixtures.read_admission(env, env["source_admission"])
    assert source["care_status"] == "TRANSFERRED"
    assert source["discharge_disposition"] == "BACK_TRANSFERRED"
    assert _same_instant(source["discharged_at"], CLOCK_START)


def test_bed_freed_at_the_source_unit_promotes_its_deferred_referral(api):
    """PRD §3.8: "The source unit — not just the admitting one — then has its bed counters, `census_posture` and `required_nurse_count` re-derived, has its deferral queue promoted, and has its `version` advanced by one."

    PRD §3.4: "Promotion then loops: while the unit's committed `available_bed_count` is at least 1 and the pool is non-empty, the top-ranked candidate is promoted `DEFERRED → ACCEPTED`, a `HELD` reservation is created for it exactly as an ordinary acceptance would (same waterfall `bed_class`, same `held_at`, same kind-dependent `expires_at`), its `decision_reason` is cleared back to null, the unit's `version` advances by one, the ledger is re-derived, and the loop continues."

    PRD §2.8: "`deferral_queue_depth` is itself the count of referrals whose `receiving_unit_id` is this unit and whose status is `DEFERRED`."

    Design: Difficulty/transitive_cascade/back_transfer_admission_cascades_to_queue_promotion
    """
    env = _back_transfer_accepted_with_a_deferred_case_behind_it(api)

    validate_success(
        api.create_admission(
            factories.admission_payload(env["onward_referral"]), env["intake_b"]
        ),
        201,
    )

    # Link 4: the queue drains at the regional unit, two entities away from the
    # community hospital the call was addressed to.
    promoted = fixtures.read_referral(env, env["waiting_referral"])
    assert promoted["status"] == "ACCEPTED"
    assert promoted["decision_reason"] is None

    source_unit = fixtures.read_unit(env, env["unit_a_id"])
    assert_unit_counts(source_unit, occupied=0, held=1, available=0)
    assert source_unit["deferral_queue_depth"] == 0

    admitting_unit = fixtures.read_unit(env, env["unit_b_id"])
    assert_unit_counts(admitting_unit, occupied=1, held=0, available=5)
