"""Validation coverage: ladder ordering, per-rule refusals and inclusive boundaries.

Every request in this API walks the single ordered ladder of §2.8, and the first
failing check is the whole response. These tests drive that ladder through real
endpoints: each scenario is built so the rule under test is either the earliest
one that can fail, or — where the PRD pins a relative order in prose — so that
two rules fail together and the winner is observable.

The logical clock is the sole notion of "now", so every temporal boundary here is
reached by moving it explicitly.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    as_run_kinds,
    factories as fc,
    fixtures as fx,
    make_engineer_headers,
    make_master_control_headers,
    validate_error,
    validate_success,
)

# The plant is bootstrapped at this instant, so a certification expiring here is
# expiring at exactly the current logical clock value.
_T0 = "2026-08-01T09:00:00Z"
_T0_PLUS_1 = "2026-08-01T09:00:01Z"


def _mco_certified_until(expires_utc):
    """Mint a master-control operator whose certification lapses at a chosen instant.

    Returns the operator row together with headers that present that operator's
    own id, which is what the entity-backed roles require.
    """
    operator = fx.create_operator("MASTER_CONTROL", "CRAWL_AND_CUTIN", expires_utc)
    return operator, make_master_control_headers(operator["id"])


def _qc_failed_asset(plant, defect_codes, ingest_score,
                     captions_required=False, caption_present=False):
    """Drive one asset to QC_FAILED carrying a known ingest score.

    The score is checked here as a precondition guard so the waiver tests below
    can reason about the score threshold without re-deriving the arithmetic.
    """
    asset = fx.setup_qc_failed_asset(
        plant, 1800,
        defect_codes=defect_codes,
        asset_overrides={"captions_required": captions_required},
        delivery_overrides={"caption_present": caption_present},
    )
    assert asset["status"] == "QC_FAILED", \
        f"precondition: asset must be QC_FAILED, got {asset['status']}"
    assert asset["technical_score_ingest"] == ingest_score, \
        (f"precondition: ingest score must be {ingest_score}, got "
         f"{asset['technical_score_ingest']}")
    return asset


def _waiver_payload(plant, justification):
    """A waiver signed by the programme director, whose role class may waive."""
    return {
        "waived_by_operator_id": plant["pd"]["id"],
        "waiver_justification": justification,
    }


def _guaranteed_cutin_rig():
    """Channel 12.1 on air over a 200-second day whose trailing spot is guaranteed.

    Element one (PROGRAM, 100 s) is playing from 15:00:00Z and element two
    (COMMERCIAL, 100 s, booked 15:01:40Z to 15:03:20Z) belongs to a single-spot
    GUARANTEED order of 100000 cents. The clock is left at 15:00:30Z and a
    PENDING cut-in of 300 seconds is waiting, so the commercial's whole booked
    span lies inside the override's expected span.
    """
    plant = fx.setup_base_plant()
    programme = fx.setup_qc_passed_asset(plant, 100)
    spot = fx.setup_qc_passed_asset(plant, 100)
    plant["order"] = fx.create_order(
        plant,
        ordered_spots=1,
        unit_duration_seconds=100,
        rate_cents_total=100000,
        priority_class="GUARANTEED",
    )
    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": programme["id"],
         "scheduled_start_utc": "2026-08-01T15:00:00Z",
         "scheduled_duration_seconds": 100},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": spot["id"], "spot_order_id": plant["order"]["id"],
         "scheduled_start_utc": "2026-08-01T15:01:40Z",
         "scheduled_duration_seconds": 100},
    ]
    plant["playlist"] = fx.ingest(
        plant, items,
        schedule_start_utc="2026-08-01T15:00:00Z",
        window_duration_seconds=200,
    )
    fx.drive_playlist(plant, plant["playlist"]["id"], "VALIDATED")
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    fx.drive_playlist(plant, plant["playlist"]["id"], "ARMED")
    fx.set_clock("2026-08-01T14:59:00Z")
    plant["playlist"] = fx.drive_playlist(plant, plant["playlist"]["id"], "ON_AIR")
    plant["items"] = fx.list_items(plant["playlist"]["id"], plant["traffic_headers"])

    fx.set_clock("2026-08-01T15:00:00Z")
    fx.cue_item(plant, plant["items"][0]["id"], "2026-08-01T15:00:00Z")
    fx.start_item(plant, plant["items"][0]["id"], "2026-08-01T15:00:00Z")
    fx.set_clock("2026-08-01T15:00:30Z")
    plant["override"] = fx.request_override(
        plant, "CUT_IN", plant["ch1"]["id"],
        requested_start_utc="2026-08-01T15:00:30Z",
        expected_duration_seconds=300,
    )
    return plant


# ===========================================================================
# Authentication, identity and actor fitness (ladder rules 1 to 7)
# ===========================================================================

def test_absent_and_empty_auth_headers_outrank_a_malformed_body(api):
    """Missing or blank credentials are reported before the body is looked at.

    PRD §2.1: "A request that omits either header, or supplies either as an empty string, is rejected with `ERR_MISSING_AUTH_HEADERS` before the body is parsed at all, so a request that is both unauthenticated and malformed reports the missing headers rather than the malformed body."

    Design: Corner/validations/auth_ladder_1_to_7_is_evaluated_in_priority_order
    """
    plant = fx.setup_base_plant()
    malformed = {"target_air_status": "STANDBY"}

    omitted = api.change_channel_air_state(plant["ch1"]["id"], malformed, {})
    validate_error(omitted, "ERR_MISSING_AUTH_HEADERS")

    blank = api.change_channel_air_state(
        plant["ch1"]["id"], malformed,
        {"X-User-ID": "", "X-User-Role": "MasterControlOperator"},
    )
    validate_error(blank, "ERR_MISSING_AUTH_HEADERS")


def test_role_header_is_matched_case_sensitively(api):
    """A role spelled in the wrong case is not one of the seven known names.

    PRD §2.1: "The value of `X-User-Role` is matched case-sensitively against exactly seven role names — `MasterControlOperator`, `QCTechnician`, `ProgramDirector`, `BroadcastEngineer`, `TrafficCoordinator`, `ComplianceOfficer` and `StationAdmin` — and anything outside that set is rejected with `ERR_UNKNOWN_ROLE`."

    Design: Corner/validations/auth_ladder_1_to_7_is_evaluated_in_priority_order
    """
    plant = fx.setup_base_plant()
    resp = api.change_channel_air_state(
        plant["ch1"]["id"], {"target_air_status": "ON_AIR"},
        {"X-User-ID": plant["mco"]["id"], "X-User-Role": "mastercontroloperator"},
    )
    validate_error(resp, "ERR_UNKNOWN_ROLE")


def test_entity_backed_role_with_an_unresolvable_user_id_is_refused(api):
    """An entity-backed role must name a persisted operator row.

    PRD §2.1: "If `X-User-ID` does not resolve to an existing `Operator` row while one of those four roles is claimed, the request fails with `ERR_OPERATOR_NOT_FOUND`."

    Design: Corner/validations/auth_ladder_1_to_7_is_evaluated_in_priority_order
    """
    plant = fx.setup_base_plant()
    resp = api.change_channel_air_state(
        plant["ch1"]["id"], {"target_air_status": "ON_AIR"},
        TEST_USERS["master_control_headers"],
    )
    validate_error(resp, "ERR_OPERATOR_NOT_FOUND")


def test_role_class_disagreement_outranks_endpoint_authorisation(api):
    """A QC operator claiming the engineer role fails identity, not authorisation.

    PRD §2.1: "A genuine operator presenting the wrong role class is stopped at identity verification, not at authorisation."

    Design: Corner/validations/auth_ladder_1_to_7_is_evaluated_in_priority_order
    """
    plant = fx.setup_base_plant()
    resp = api.change_channel_air_state(
        plant["ch1"]["id"], {"target_air_status": "ON_AIR"},
        make_engineer_headers(plant["qc"]["id"]),
    )
    validate_error(resp, "ERR_ROLE_IDENTITY_MISMATCH")


def test_recognised_role_outside_the_endpoint_list_is_refused(api):
    """A QC technician may not command a channel's air state.

    PRD §2.1: "Once the role is recognised, the endpoint's own permitted-role list governs: a recognised role attempting an operation it does not own is rejected with `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/validations/auth_ladder_1_to_7_is_evaluated_in_priority_order
    """
    plant = fx.setup_base_plant()
    resp = api.change_channel_air_state(
        plant["ch1"]["id"], {"target_air_status": "ON_AIR"}, plant["qc_headers"],
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_operator_suspension_outranks_the_state_precondition(api):
    """A suspended operator asking for an unreachable air state hears about the suspension.

    PRD §2.8: "**Suspension outranks state.** A suspended operator calling a mutation on a resource that is also in the wrong state receives `ERR_OPERATOR_SUSPENDED`, never the state error."

    Design: Corner/validations/auth_ladder_1_to_7_is_evaluated_in_priority_order
    """
    plant = fx.setup_base_plant()
    fx.suspend_operator(plant["mco"]["id"])

    resp = api.change_channel_air_state(
        plant["ch1"]["id"], {"target_air_status": "BARS_AND_TONE"},
        plant["mco_headers"],
    )
    validate_error(resp, "ERR_OPERATOR_SUSPENDED")


def test_suspended_operator_keeps_read_access(api):
    """Suspension bars mutations only; reads stay open.

    PRD §2.1: "A suspended operator — one whose `status` is `SUSPENDED` rather than `ACTIVE` — is refused every mutating request with `ERR_OPERATOR_SUSPENDED`, while read endpoints remain available to them."

    Design: Corner/validations/auth_ladder_1_to_7_is_evaluated_in_priority_order
    """
    plant = fx.setup_base_plant()
    fx.suspend_operator(plant["mco"]["id"])

    refused = api.change_channel_air_state(
        plant["ch1"]["id"], {"target_air_status": "ON_AIR"}, plant["mco_headers"],
    )
    validate_error(refused, "ERR_OPERATOR_SUSPENDED")

    allowed = api.get_channel(plant["ch1"]["id"], plant["mco_headers"])
    validate_success(allowed)


def test_certification_expiring_at_the_clock_instant_still_takes_a_channel_to_air(api):
    """The expiry instant itself is inside the certification.

    PRD §2.1: "Certification is treated as valid at exactly `certification_expires_utc` and expired one second later."

    Design: Corner/validations/auth_ladder_1_to_7_is_evaluated_in_priority_order
    """
    plant = fx.setup_base_plant()
    _, boundary_headers = _mco_certified_until(_T0)

    resp = api.change_channel_air_state(
        plant["ch1"]["id"], {"target_air_status": "ON_AIR"}, boundary_headers,
    )
    data = validate_success(resp)
    assert data["air_status"] == "ON_AIR", \
        f"the channel should be lit, got air_status {data['air_status']}"


def test_certification_one_second_past_expiry_blocks_the_air_state_change(api):
    """One second past the expiry instant the same operator is no longer certified.

    PRD §2.1: "Certification is treated as valid at exactly `certification_expires_utc` and expired one second later."

    Design: Corner/validations/auth_ladder_1_to_7_is_evaluated_in_priority_order
    """
    plant = fx.setup_base_plant()
    _, boundary_headers = _mco_certified_until(_T0)
    fx.set_clock(_T0_PLUS_1)

    resp = api.change_channel_air_state(
        plant["ch1"]["id"], {"target_air_status": "ON_AIR"}, boundary_headers,
    )
    validate_error(resp, "ERR_OPERATOR_CERTIFICATION_EXPIRED")


def test_certification_state_is_re_derived_across_the_expiry_instant(api):
    """The derived certification enum flips only once the clock has moved past expiry.

    PRD §2.4: "`certification_state` is a derived enum with exactly two values, `VALID` and `EXPIRED`: it reads `VALID` while the logical clock is at or before `certification_expires_utc`, and `EXPIRED` once the clock has moved past it."

    Design: Corner/validations/auth_ladder_1_to_7_is_evaluated_in_priority_order
    """
    fx.bootstrap_operators()
    boundary, _ = _mco_certified_until(_T0)
    assert fx.read_operator(boundary["id"])["certification_state"] == "VALID", \
        "at exactly the expiry instant the certification still reads VALID"

    fx.set_clock(_T0_PLUS_1)
    assert fx.read_operator(boundary["id"])["certification_state"] == "EXPIRED", \
        "one second past the expiry instant the certification reads EXPIRED"


def test_expired_certification_still_permits_reads(api):
    """Certification gates air-critical mutations, never reads.

    PRD §3.4: "Read operations are never gated on certification."

    Design: Corner/validations/auth_ladder_1_to_7_is_evaluated_in_priority_order
    """
    plant = fx.setup_base_plant()
    expired, expired_headers = _mco_certified_until(_T0)
    fx.set_clock(_T0_PLUS_1)

    validate_success(api.get_channel(plant["ch1"]["id"], expired_headers))
    validate_success(api.get_operator(expired["id"], expired_headers))


# ===========================================================================
# Field shape, existence, concurrency and state (ladder rules 8 to 24)
# ===========================================================================

def _passed_asset_plant():
    """Base plant plus one asset already graded to QC_PASSED.

    A second ingest-basis report against that asset is an illegal move, which is
    what lets the earlier ladder bands be observed winning over the state rule.
    """
    plant = fx.setup_base_plant()
    plant["asset"] = fx.setup_qc_passed_asset(plant)
    return plant


def test_missing_required_field_outranks_an_invalid_enum(api):
    """An omitted concurrency field is reported before a bad enum literal.

    PRD §2.8: "required fields present (`ERR_MISSING_REQUIRED_FIELD`), enum literals valid (`ERR_INVALID_ENUM_VALUE`), types and ranges valid (`ERR_INVALID_FIELD_VALUE`)"

    Design: Corner/validations/field_shape_then_existence_then_occ_then_state_ladder
    """
    plant = _passed_asset_plant()
    resp = api.submit_qc_report(
        plant["asset"]["id"],
        {
            "inspected_by_operator_id": plant["qc"]["id"],
            "basis": "SCREENING",
            "defect_codes": [],
            "measured_duration_seconds": 1800,
        },
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_MISSING_REQUIRED_FIELD")


def test_invalid_enum_outranks_an_out_of_range_value(api):
    """A bad enum literal is reported before an out-of-range duration.

    PRD §2.8: "required fields present (`ERR_MISSING_REQUIRED_FIELD`), enum literals valid (`ERR_INVALID_ENUM_VALUE`), types and ranges valid (`ERR_INVALID_FIELD_VALUE`)"

    Design: Corner/validations/field_shape_then_existence_then_occ_then_state_ladder
    """
    plant = _passed_asset_plant()
    resp = api.submit_qc_report(
        plant["asset"]["id"],
        fc.qc_report_payload(
            plant["asset"]["version"], plant["qc"]["id"],
            basis="SCREENING", measured_duration_seconds=-5,
        ),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_INVALID_ENUM_VALUE")


def test_out_of_range_value_outranks_an_unresolvable_body_reference(api):
    """A negative duration is reported before an unknown inspector reference.

    PRD §2.8: "required fields present (`ERR_MISSING_REQUIRED_FIELD`), enum literals valid (`ERR_INVALID_ENUM_VALUE`), types and ranges valid (`ERR_INVALID_FIELD_VALUE`), path segments resolve (the per-segment 404 codes of §2.7), body references resolve (the same 404 codes)"

    Design: Corner/validations/field_shape_then_existence_then_occ_then_state_ladder
    """
    plant = _passed_asset_plant()
    resp = api.submit_qc_report(
        plant["asset"]["id"],
        fc.qc_report_payload(
            plant["asset"]["version"], NON_EXISTENT_UUID,
            measured_duration_seconds=-5,
        ),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_INVALID_FIELD_VALUE")


def test_unresolvable_path_segment_outranks_an_unresolvable_body_reference(api):
    """The asset in the path is resolved before the inspector in the body.

    PRD §2.7: "References supplied inside a request body are resolved after every path segment has resolved and before any concurrency check runs."

    Design: Corner/validations/field_shape_then_existence_then_occ_then_state_ladder
    """
    plant = _passed_asset_plant()
    resp = api.submit_qc_report(
        NON_EXISTENT_UUID,
        fc.qc_report_payload(plant["asset"]["version"], NON_EXISTENT_UUID),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_ASSET_NOT_FOUND")


def test_unresolvable_body_reference_outranks_a_stale_parent_version(api):
    """The inspector reference is resolved before the version is compared.

    PRD §2.7: "References supplied inside a request body are resolved after every path segment has resolved and before any concurrency check runs."

    Design: Corner/validations/field_shape_then_existence_then_occ_then_state_ladder
    """
    plant = _passed_asset_plant()
    resp = api.submit_qc_report(
        plant["asset"]["id"],
        fc.qc_report_payload(999, NON_EXISTENT_UUID),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_OPERATOR_REFERENCE_NOT_FOUND")


def test_stale_asset_version_outranks_the_asset_state_rule(api):
    """A stale version beats the illegal-basis state rule on the same request.

    PRD §2.8: "**Stale version outranks state.** A request carrying a stale parent version against a resource that is also in the wrong state receives the 412 stale-version error, never the 409 state error."

    Design: Corner/validations/field_shape_then_existence_then_occ_then_state_ladder
    """
    plant = _passed_asset_plant()
    resp = api.submit_qc_report(
        plant["asset"]["id"],
        fc.qc_report_payload(999, plant["qc"]["id"], basis="INGEST"),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_STALE_ASSET_VERSION")


def test_state_rule_surfaces_once_the_version_is_current(api):
    """With the observed version supplied, the illegal basis is what fails.

    PRD §3.4: "An ingest-basis report requires the asset to be in `RECEIVED`; an air-check-basis report requires the asset to be in `QC_PASSED` or `QC_WAIVED`; either mismatch yields `ERR_ASSET_INVALID_STATE`."

    Design: Corner/validations/field_shape_then_existence_then_occ_then_state_ladder
    """
    plant = _passed_asset_plant()
    resp = api.submit_qc_report(
        plant["asset"]["id"],
        fc.qc_report_payload(
            plant["asset"]["version"], plant["qc"]["id"], basis="INGEST",
        ),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_ASSET_INVALID_STATE")


# ===========================================================================
# One undeclared move per state machine (ladder rules 14 to 24)
# ===========================================================================

def test_full_power_to_full_power_is_not_a_declared_transition(api):
    """The reflexive power move is refused rather than treated as a no-op.

    PRD §3.1: "Notably, `FULL_POWER` to `FULL_POWER` is not a declared transition and is refused."

    Design: Corner/validations/every_state_rule_14_to_24_rejects_its_own_undeclared_move_with_409
    """
    plant = fx.setup_base_plant()
    resp = api.change_transmitter_power_state(
        plant["transmitter"]["id"], {"target_state": "FULL_POWER"},
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_TRANSMITTER_INVALID_STATE")


def test_eas_override_cannot_be_reached_through_the_air_state_endpoint(api):
    """Even from ON_AIR the override state is not commandable directly.

    PRD §3.3: "**`EAS_OVERRIDE` is never reachable through the air-state endpoint at all** — asking for it there is refused with the same code even when the channel is `ON_AIR`, because that state belongs exclusively to the override cascade of §3.8."

    Design: Corner/validations/every_state_rule_14_to_24_rejects_its_own_undeclared_move_with_409
    """
    plant = fx.setup_base_plant()
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")

    resp = api.change_channel_air_state(
        plant["ch1"]["id"], {"target_air_status": "EAS_OVERRIDE"},
        plant["mco_headers"],
    )
    validate_error(resp, "ERR_CHANNEL_INVALID_AIR_STATE")


def test_waiver_against_a_passed_asset_is_an_illegal_move(api):
    """There is no failure to waive on an asset that passed inspection.

    PRD §3.4: "The waiver supplies `waived_by_operator_id` and a `waiver_justification`, and is legal only from `QC_FAILED`; from any other status it is refused with `ERR_ASSET_INVALID_STATE`."

    Design: Corner/validations/every_state_rule_14_to_24_rejects_its_own_undeclared_move_with_409
    """
    plant = _passed_asset_plant()
    resp = api.sign_qc_waiver(
        plant["asset"]["id"],
        _waiver_payload(plant, "Programme must air tonight; defect is cosmetic only."),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_ASSET_INVALID_STATE")


def test_on_air_playlist_cannot_be_driven_back_to_armed(api):
    """The only move out of ON_AIR is the close.

    PRD §3.5: "The reachable moves are `IMPORTING` to `IMPORTED` or `ABANDONED`; `IMPORTED` to `VALIDATED`, back to `IMPORTING`, or `ABANDONED`; `VALIDATED` to `ARMED`, back to `IMPORTED`, or `ABANDONED`; `ARMED` to `ON_AIR`, back to `IMPORTED`, or `ABANDONED`; and `ON_AIR` to `CLOSED`."

    Design: Corner/validations/every_state_rule_14_to_24_rejects_its_own_undeclared_move_with_409
    """
    scn = fx.setup_on_air_playlist()
    resp = api.change_playlist_state(
        scn["playlist"]["id"], {"target_status": "ARMED"}, scn["pd_headers"],
    )
    validate_error(resp, "ERR_PLAYLIST_INVALID_STATE")


def test_end_event_requires_a_playing_element(api):
    """An end event against a still-scheduled element is illegal.

    PRD §3.6: "An event is legal only for certain current `playout_status` values: `CUE` requires `SCHEDULED`, `START` requires `CUED`, `END` requires `PLAYING`, `TRUNCATION` requires `PLAYING`, and `SKIP` requires `SCHEDULED` or `CUED`."

    Design: Corner/validations/every_state_rule_14_to_24_rejects_its_own_undeclared_move_with_409
    """
    scn = fx.setup_on_air_playlist()
    resp = api.post_playout_event(
        scn["items"][0]["id"],
        {"event_kind": "END", "event_utc": "2026-08-01T11:59:00Z",
         "measured_duration_seconds": 1800},
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_ITEM_INVALID_PLAYOUT_STATE")


def test_only_one_element_of_a_playlist_may_be_cued(api):
    """A second cue while another element is already cued is refused.

    PRD §3.6: "and **no other element of the same playlist may already be `CUED`**, otherwise `ERR_ITEM_INVALID_PLAYOUT_STATE`."

    Design: Corner/validations/every_state_rule_14_to_24_rejects_its_own_undeclared_move_with_409
    """
    scn = fx.setup_on_air_playlist()
    fx.cue_item(scn, scn["items"][0]["id"], "2026-08-01T11:59:00Z")

    resp = api.post_playout_event(
        scn["items"][1]["id"],
        {"event_kind": "CUE", "event_utc": "2026-08-01T11:59:00Z"},
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_ITEM_INVALID_PLAYOUT_STATE")


def test_detected_fault_cannot_jump_straight_to_mitigated(api):
    """Mitigation is reachable only from ACKNOWLEDGED or ESCALATED.

    PRD §3.3: "The reachable moves are `DETECTED` to `ACKNOWLEDGED` or to `AUTO_CLEARED`; `ACKNOWLEDGED` to `ESCALATED` or to `MITIGATED`; `ESCALATED` to `MITIGATED`; and `MITIGATED` to `RESOLVED` or back to `DETECTED`."

    Design: Corner/validations/every_state_rule_14_to_24_rejects_its_own_undeclared_move_with_409
    """
    plant = fx.setup_base_plant()
    fault = fx.report_channel_fault(plant, "AUDIO_LOSS", "MAJOR", _T0)

    resp = api.change_fault_state(
        fault["id"],
        {"target_state": "MITIGATED", "mitigation_code": "SWITCH_TO_BACKUP"},
        plant["mco_headers"],
    )
    validate_error(resp, "ERR_FAULT_INVALID_STATE")


# ===========================================================================
# Waiver safety rules and their two inclusive boundaries (rules 28, 32 to 34)
# ===========================================================================

def test_missing_caption_track_blocks_a_waiver_on_a_high_score(api):
    """An uncaptioned asset scoring 80 is still refused the waiver.

    PRD §3.4: "a missing caption track is a non-waivable defect and the waiver is refused with `ERR_CAPTION_REQUIREMENT_UNMET` regardless of how high the technical score is."

    Design: Corner/validations/waiver_safety_ladder_28_32_33_34_and_the_two_inclusive_boundaries
    """
    plant = fx.setup_base_plant()
    asset = _qc_failed_asset(
        plant, ["CAPTION_MISSING"], 80,
        captions_required=True, caption_present=False,
    )

    resp = api.sign_qc_waiver(
        asset["id"],
        _waiver_payload(plant, "Late feed; captions to follow from the supplier."),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_CAPTION_REQUIREMENT_UNMET")


def test_caption_safety_outranks_the_waiver_score_floor(api):
    """An uncaptioned asset below the floor reports the caption code, not the score code.

    PRD §2.8: "an asset that requires captions, has none, and also scores below the waiver floor reports `ERR_CAPTION_REQUIREMENT_UNMET`, not `ERR_QC_WAIVER_SCORE_TOO_LOW`."

    Design: Corner/validations/waiver_safety_ladder_28_32_33_34_and_the_two_inclusive_boundaries
    """
    plant = fx.setup_base_plant()
    asset = _qc_failed_asset(
        plant,
        ["AUDIO_LOSS", "BLACK_FRAMES", "VIDEO_ARTIFACT", "CAPTION_MISTIMED"], 39,
        captions_required=True, caption_present=False,
    )

    resp = api.sign_qc_waiver(
        asset["id"],
        _waiver_payload(plant, "Only feed available for tonight's transmission."),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_CAPTION_REQUIREMENT_UNMET")


def test_score_of_thirty_nine_is_below_the_waiver_floor(api):
    """With captions in order, a score one point short of the floor is refused.

    PRD §3.4: "The governing non-superseded ingest score in `technical_score_ingest` must be at least 40 — **exactly 40 is waivable, 39 is not** — otherwise `ERR_QC_WAIVER_SCORE_TOO_LOW`."

    Design: Corner/validations/waiver_safety_ladder_28_32_33_34_and_the_two_inclusive_boundaries
    """
    plant = fx.setup_base_plant()
    asset = _qc_failed_asset(
        plant,
        ["AUDIO_LOSS", "BLACK_FRAMES", "VIDEO_ARTIFACT", "CAPTION_MISTIMED"], 39,
        captions_required=True, caption_present=True,
    )

    resp = api.sign_qc_waiver(
        asset["id"],
        _waiver_payload(plant, "Only feed available for tonight's transmission."),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_QC_WAIVER_SCORE_TOO_LOW")


def test_justification_of_nineteen_characters_is_too_short(api):
    """One character short of the minimum justification is refused.

    PRD §3.4: "The `waiver_justification` must be at least 20 characters — **exactly 20 is accepted, 19 is not** — otherwise `ERR_WAIVER_JUSTIFICATION_REQUIRED`."

    Design: Corner/validations/waiver_safety_ladder_28_32_33_34_and_the_two_inclusive_boundaries
    """
    plant = fx.setup_base_plant()
    asset = _qc_failed_asset(
        plant, ["AUDIO_LOSS", "CAPTION_MISSING", "FORMAT_MISMATCH"], 40,
    )
    justification = "Airs tonight; minor"
    assert len(justification) == 19, "precondition: justification must be 19 characters"

    resp = api.sign_qc_waiver(
        asset["id"], _waiver_payload(plant, justification), plant["pd_headers"],
    )
    validate_error(resp, "ERR_WAIVER_JUSTIFICATION_REQUIRED")


def test_score_of_forty_with_a_twenty_character_justification_is_waivable(api):
    """Both inclusive boundaries met at once grants the waiver.

    PRD §3.4: "A granted waiver writes `waived_by_operator_id` and `waiver_justification`, moves the asset to `QC_WAIVED`, flips every item referencing the asset whose `clearance_status` is `BLOCKED` and whose `playout_status` is `SCHEDULED` or `CUED` to `CLEARED`, and decrements each owning playlist's `blocked_item_count` accordingly."

    Design: Corner/validations/waiver_safety_ladder_28_32_33_34_and_the_two_inclusive_boundaries
    """
    plant = fx.setup_base_plant()
    asset = _qc_failed_asset(
        plant, ["AUDIO_LOSS", "CAPTION_MISSING", "FORMAT_MISMATCH"], 40,
    )
    justification = "Airs tonight; minor."
    assert len(justification) == 20, "precondition: justification must be 20 characters"

    waived = fx.sign_waiver(plant, asset["id"], waiver_justification=justification)
    assert waived["status"] == "QC_WAIVED", \
        f"expected QC_WAIVED at the inclusive boundaries, got {waived['status']}"
    assert waived["waived_by_operator_id"] == plant["pd"]["id"]
    assert waived["waiver_justification"] == justification


# ===========================================================================
# As-run time order, future timestamps and clock monotonicity (rules 35 to 39)
# ===========================================================================

def test_event_one_second_ahead_of_the_clock_is_refused(api):
    """A future-dated event cannot be logged.

    PRD §3.6: "`event_utc` must also be at or before the logical clock; a future-dated event is refused with `ERR_EVENT_TIMESTAMP_IN_FUTURE`."

    Design: Corner/validations/as_run_time_order_beats_future_timestamps_and_the_clock_never_repeats
    """
    scn = fx.setup_playing_item1()
    resp = api.post_playout_event(
        scn["items"][0]["id"],
        {"event_kind": "END", "event_utc": "2026-08-01T12:00:01Z",
         "measured_duration_seconds": 1800},
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_EVENT_TIMESTAMP_IN_FUTURE")


def test_event_earlier_than_the_last_as_run_entry_is_refused(api):
    """The as-run log is append-only in time order.

    PRD §3.6: "`event_utc` must be at or after the `event_utc` of the most recent as-run entry for the same playlist, because the log is append-only in time order; an out-of-order event is refused with `ERR_PLAYOUT_EVENT_OUT_OF_ORDER`."

    Design: Corner/validations/as_run_time_order_beats_future_timestamps_and_the_clock_never_repeats
    """
    scn = fx.setup_playing_item1()
    resp = api.post_playout_event(
        scn["items"][0]["id"],
        {"event_kind": "END", "event_utc": "2026-08-01T11:59:59Z",
         "measured_duration_seconds": 1800},
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_PLAYOUT_EVENT_OUT_OF_ORDER")


def test_clock_never_repeats_or_rewinds(api):
    """Neither the present instant nor an earlier one may be set again.

    PRD §2.4: "A clock advance must move strictly forward: a request whose `current_utc` equals or precedes the present clock value is rejected with `ERR_CLOCK_NOT_MONOTONIC`."

    Design: Corner/validations/as_run_time_order_beats_future_timestamps_and_the_clock_never_repeats
    """
    fx.setup_playing_item1()

    repeat = api.set_clock("2026-08-01T12:00:00Z", TEST_USERS["admin_headers"])
    validate_error(repeat, "ERR_CLOCK_NOT_MONOTONIC")

    rewind = api.set_clock("2026-08-01T11:59:59Z", TEST_USERS["admin_headers"])
    validate_error(rewind, "ERR_CLOCK_NOT_MONOTONIC")


def test_event_exactly_at_the_clock_and_at_the_previous_entry_is_accepted(api):
    """The inclusive instant satisfies both timestamp rules at once.

    PRD §3.6: "An `event_utc` exactly equal to the logical clock is accepted, and an `event_utc` exactly equal to the previous entry's `event_utc` is accepted."

    Design: Corner/validations/as_run_time_order_beats_future_timestamps_and_the_clock_never_repeats
    """
    scn = fx.setup_playing_item1()
    validate_success(
        api.post_playout_event(
            scn["items"][0]["id"],
            {"event_kind": "END", "event_utc": "2026-08-01T12:00:00Z",
             "measured_duration_seconds": 1800},
            scn["mco_headers"],
        ),
        201,
    )

    entries = fx.list_as_run(scn["playlist"]["id"], scn["mco_headers"])
    assert as_run_kinds(entries) == ["CUE", "START", "END"], \
        f"expected the three events in order, got {as_run_kinds(entries)}"


# ===========================================================================
# Delivery grace window, the expiry sweep and redelivery (rules 40 to 44)
# ===========================================================================

def test_delivery_exactly_at_the_deadline_is_on_time(api):
    """The deadline instant itself is not late.

    PRD §3.4: "**a `received_utc` exactly at the deadline is on time and carries `late_delivery` false, one second past the deadline is late but still accepted, and the deadline plus 3600 seconds is the last instant that is accepted at all**"

    Design: Corner/validations/delivery_grace_window_then_expiry_sweep_then_redelivery_refusal
    """
    plant = fx.setup_base_plant()
    asset = fx.create_asset(plant, delivery_deadline_utc="2026-08-01T10:00:00Z")
    fx.set_clock("2026-08-01T10:00:00Z")

    delivered = fx.deliver_asset(
        plant, asset["id"], received_utc="2026-08-01T10:00:00Z",
    )
    assert delivered["status"] == "RECEIVED", \
        f"expected RECEIVED after an on-time delivery, got {delivered['status']}"
    assert delivered["late_delivery"] is False, \
        "a delivery at exactly the deadline must not be flagged late"


def test_delivery_at_the_last_instant_of_the_grace_is_late_but_accepted(api):
    """The deadline plus 3600 seconds is still admitted, flagged late.

    PRD §3.4: "**a `received_utc` exactly at the deadline is on time and carries `late_delivery` false, one second past the deadline is late but still accepted, and the deadline plus 3600 seconds is the last instant that is accepted at all**"

    Design: Corner/validations/delivery_grace_window_then_expiry_sweep_then_redelivery_refusal
    """
    plant = fx.setup_base_plant()
    asset = fx.create_asset(plant, delivery_deadline_utc="2026-08-01T10:00:00Z")
    fx.set_clock("2026-08-01T11:00:00Z")

    delivered = fx.deliver_asset(
        plant, asset["id"], received_utc="2026-08-01T11:00:00Z",
    )
    assert delivered["status"] == "RECEIVED", \
        f"expected RECEIVED at the last legal instant, got {delivered['status']}"
    assert delivered["late_delivery"] is True, \
        "a delivery an hour past the deadline must be flagged late"


def test_still_expected_asset_expires_one_second_past_the_grace(api):
    """The checkpoint sweeps an undelivered asset to its terminal status.

    PRD §3.4: "When the logical clock advances past `delivery_deadline_utc` plus 3600 seconds and the asset is still `EXPECTED`, it moves to `EXPIRED`, which is terminal"

    Design: Corner/validations/delivery_grace_window_then_expiry_sweep_then_redelivery_refusal
    """
    plant = fx.setup_base_plant()
    asset = fx.create_asset(plant, delivery_deadline_utc="2026-08-01T10:00:00Z")
    assert asset["status"] == "EXPECTED", \
        f"precondition: a fresh asset is EXPECTED, got {asset['status']}"

    fx.set_clock("2026-08-01T11:00:01Z")

    swept = fx.read_asset(asset["id"], plant["traffic_headers"])
    assert swept["status"] == "EXPIRED", \
        f"expected EXPIRED one second past the grace, got {swept['status']}"


def test_sweep_leaves_a_delivered_but_failed_asset_alone(api):
    """Only assets still merely expected are swept to expiry.

    PRD §2.4: "Every asset still merely expected whose delivery grace window has elapsed moves to `EXPIRED`, dragging its clearance cascade with it."

    Design: Corner/validations/delivery_grace_window_then_expiry_sweep_then_redelivery_refusal
    """
    plant = fx.setup_base_plant()
    asset = fx.setup_qc_failed_asset(plant, 1800)
    assert asset["status"] == "QC_FAILED", \
        f"precondition: asset must be QC_FAILED, got {asset['status']}"

    fx.set_clock("2026-08-01T11:00:01Z")

    after = fx.read_asset(asset["id"], plant["traffic_headers"])
    assert after["status"] == "QC_FAILED", \
        f"a delivered asset must survive the expiry sweep, got {after['status']}"


def test_redelivery_beyond_the_grace_is_refused(api):
    """A replacement file timestamped past the grace cannot be recorded.

    PRD §3.4: "and a delivery whose `received_utc` itself lies beyond that grace is refused with the same code even if the sweep has not yet run."

    Design: Corner/validations/delivery_grace_window_then_expiry_sweep_then_redelivery_refusal
    """
    plant = fx.setup_base_plant()
    # The deadline is pinned here rather than inherited, because this test is about
    # the grace boundary itself: with a 10:00:00Z deadline the grace closes at
    # 11:00:00Z, so the 11:00:01Z replacement file lies one second beyond it.
    asset = fx.setup_qc_failed_asset(
        plant, 1800,
        asset_overrides={"delivery_deadline_utc": "2026-08-01T10:00:00Z"},
    )
    fx.set_clock("2026-08-01T11:00:01Z")

    resp = api.record_asset_delivery(
        asset["id"], fc.delivery_payload(received_utc="2026-08-01T11:00:01Z"),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_DELIVERY_DEADLINE_PASSED")


# ===========================================================================
# Structural and uniqueness constraints (rules 47 to 55)
# ===========================================================================

def _second_multiplex(plant):
    """A second transport stream on the same transmitter, for cross-stream probes."""
    return fx.create_multiplex(
        plant["eng_headers"], plant["transmitter"]["id"], name="MUX-B",
    )


def test_channel_number_is_unique_across_every_multiplex(api):
    """The same virtual number cannot be claimed on a second transport stream.

    PRD §3.2: "`channel_number` is unique across the entire station and across all multiplexes, so two subchannels can never both claim 5.2; a collision yields `ERR_DUPLICATE_CHANNEL_NUMBER`."

    Design: Corner/validations/channel_shape_and_uniqueness_constraints_47_to_55_each_own_their_error
    """
    plant = fx.setup_base_plant()
    mux_b = _second_multiplex(plant)

    resp = api.create_channel(
        fc.create_channel_payload(
            mux_b["id"], mux_b["version"],
            call_sign="WXYZ-DT8", channel_number=plant["ch1"]["channel_number"],
        ),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_DUPLICATE_CHANNEL_NUMBER")


def test_subchannel_without_a_parent_is_refused(api):
    """A subchannel must name the primary it hangs off.

    PRD §3.2: "A `service_class` of `SUBCHANNEL` submitted without a `parent_channel_id` yields `ERR_SUBCHANNEL_PARENT_REQUIRED`"

    Design: Corner/validations/channel_shape_and_uniqueness_constraints_47_to_55_each_own_their_error
    """
    plant = fx.setup_base_plant()
    resp = api.create_channel(
        fc.create_channel_payload(
            plant["multiplex"]["id"], plant["multiplex"]["version"],
            call_sign="WXYZ-DT5", channel_number="12.5",
            service_class="SUBCHANNEL", resolution_class="SD_480I",
            requested_bitrate_kbps=6000, floor_bitrate_kbps=2000, priority_rank=3,
        ),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_SUBCHANNEL_PARENT_REQUIRED")


def test_primary_channel_with_a_parent_is_refused(api):
    """Which of the two parent-shape codes applies is chosen by the service class.

    PRD §3.2: "a `service_class` of `PRIMARY` submitted *with* a `parent_channel_id` yields `ERR_PRIMARY_CHANNEL_PARENT_FORBIDDEN` — which of the two codes applies is selected by the submitted `service_class`."

    Design: Corner/validations/channel_shape_and_uniqueness_constraints_47_to_55_each_own_their_error
    """
    plant = fx.setup_base_plant()
    resp = api.create_channel(
        fc.create_channel_payload(
            plant["multiplex"]["id"], plant["multiplex"]["version"],
            call_sign="WXYZ-DT4", channel_number="12.4",
            parent_channel_id=plant["ch1"]["id"],
        ),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_PRIMARY_CHANNEL_PARENT_FORBIDDEN")


def test_subchannel_may_not_parent_another_subchannel(api):
    """The parent chain is exactly one level deep.

    PRD §3.2: "The parent chain is exactly one level deep: `parent_channel_id` must reference a channel whose own `service_class` is `PRIMARY`, so a subchannel may not parent another subchannel and no channel may reference itself; a violation yields `ERR_INVALID_CHANNEL_PARENT`."

    Design: Corner/validations/channel_shape_and_uniqueness_constraints_47_to_55_each_own_their_error
    """
    plant = fx.setup_base_plant()
    resp = api.create_channel(
        fc.create_subchannel_payload(
            plant["multiplex"]["id"], plant["multiplex"]["version"],
            plant["ch2"]["id"],
            call_sign="WXYZ-DT3", channel_number="12.3", priority_rank=3,
        ),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_INVALID_CHANNEL_PARENT")


def test_parent_on_another_transport_stream_is_refused(api):
    """A subchannel cannot hang off a primary carried elsewhere.

    PRD §3.2: "And the parent must sit on the same multiplex as the `multiplex_id` supplied in the body, because a subchannel cannot hang off a primary carried by another transmitter's transport stream; a cross-stream parent yields `ERR_CROSS_MULTIPLEX_PARENT`."

    Design: Corner/validations/channel_shape_and_uniqueness_constraints_47_to_55_each_own_their_error
    """
    plant = fx.setup_base_plant()
    mux_b = _second_multiplex(plant)

    resp = api.create_channel(
        fc.create_subchannel_payload(
            mux_b["id"], mux_b["version"], plant["ch1"]["id"],
            call_sign="WXYZ-DT9", channel_number="12.9", priority_rank=3,
        ),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_CROSS_MULTIPLEX_PARENT")


def test_floor_above_the_request_is_refused(api):
    """A channel cannot demand a floor higher than what it asks for.

    PRD §3.2: "`floor_bitrate_kbps` may not exceed `requested_bitrate_kbps`; equality is legal and makes the channel an all-or-nothing claimant in the waterfall, while a floor above the request yields `ERR_BITRATE_FLOOR_EXCEEDS_REQUEST`."

    Design: Corner/validations/channel_shape_and_uniqueness_constraints_47_to_55_each_own_their_error
    """
    plant = fx.setup_base_plant()
    resp = api.create_channel(
        fc.create_channel_payload(
            plant["multiplex"]["id"], plant["multiplex"]["version"],
            call_sign="WXYZ-DT6", channel_number="12.6", priority_rank=3,
            resolution_class="HD_1080I",
            floor_bitrate_kbps=9000, requested_bitrate_kbps=8500,
        ),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_BITRATE_FLOOR_EXCEEDS_REQUEST")


def test_floor_one_kilobit_below_the_resolution_minimum_is_refused(api):
    """Standard definition may not floor below its 2000 kbps minimum.

    PRD §3.2: "And `floor_bitrate_kbps` must be at least the minimum for its `resolution_class` — 8000 for `HD_1080I`, 5000 for `HD_720P`, 2000 for `SD_480I` — where exactly the minimum is legal and one kilobit below it is not, yielding `ERR_BITRATE_FLOOR_BELOW_RESOLUTION_MINIMUM`."

    Design: Corner/validations/channel_shape_and_uniqueness_constraints_47_to_55_each_own_their_error
    """
    plant = fx.setup_base_plant()
    resp = api.create_channel(
        fc.create_channel_payload(
            plant["multiplex"]["id"], plant["multiplex"]["version"],
            call_sign="WXYZ-DT7", channel_number="12.7", priority_rank=3,
            resolution_class="SD_480I",
            floor_bitrate_kbps=1999, requested_bitrate_kbps=6000,
        ),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_BITRATE_FLOOR_BELOW_RESOLUTION_MINIMUM")


def test_house_number_is_never_recycled_after_retraction(api):
    """Withdrawing an asset does not free its house number.

    PRD §3.4: "`house_number` is unique across every asset ever registered **including retracted and expired ones — a house number is never recycled**, and a collision yields `ERR_DUPLICATE_HOUSE_NUMBER`."

    Design: Corner/validations/channel_shape_and_uniqueness_constraints_47_to_55_each_own_their_error
    """
    plant = fx.setup_base_plant()
    first = fx.create_asset(plant, house_number="HN-NEVER-RECYCLED")
    retracted = fx.retract(plant, first["id"])
    assert retracted["status"] == "RETRACTED", \
        f"precondition: asset must be RETRACTED, got {retracted['status']}"

    resp = api.create_asset(
        fc.create_asset_payload(house_number="HN-NEVER-RECYCLED"),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_DUPLICATE_HOUSE_NUMBER")


def test_order_reference_is_unique_across_all_orders(api):
    """The traffic system's reference identifies exactly one order.

    PRD §3.9: "`order_reference` is unique across all orders and a collision yields `ERR_DUPLICATE_ORDER_REFERENCE`."

    Design: Corner/validations/channel_shape_and_uniqueness_constraints_47_to_55_each_own_their_error
    """
    plant = fx.setup_base_plant()
    fx.create_order(plant, order_reference="ORD-UNIQUE-01")

    resp = api.create_spot_order(
        fc.create_spot_order_payload(
            plant["ch1"]["id"], order_reference="ORD-UNIQUE-01",
        ),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_DUPLICATE_ORDER_REFERENCE")


# ===========================================================================
# Referential coherence and the fiscal preemption gate (rules 59 to 65)
# ===========================================================================

def test_plant_level_fault_requires_a_transmitter_target(api):
    """A loss of signal reported against a service alone is incoherent.

    PRD §3.3: "a fault coded `RF_POWER_FAULT` or `LOSS_OF_SIGNAL` requires a `transmitter_id` because those conditions are properties of the plant rather than of a service; and a fault coded `AUDIO_LOSS`, `BLACK_FRAME` or `CAPTION_LOSS` requires a `channel_id` because those are observed on a service. Any of those mismatches yields `ERR_FAULT_TARGET_MISMATCH`."

    Design: Corner/validations/referential_and_preemption_rules_59_to_65_reject_cross_entity_mismatches
    """
    plant = fx.setup_base_plant()
    resp = api.report_fault(
        fc.report_fault_payload(
            "LOSS_OF_SIGNAL", "CRITICAL", _T0, channel_id=plant["ch1"]["id"],
        ),
        plant["mco_headers"],
    )
    validate_error(resp, "ERR_FAULT_TARGET_MISMATCH")


def test_inspecting_operator_must_hold_the_qc_role_class(api):
    """An engineer cannot be named as the inspector of a QC report.

    PRD §3.4: "`inspected_by_operator_id` must reference an operator whose `role_class` is `QC` and whose `status` is `ACTIVE`; a wrong role class yields `ERR_OPERATOR_ROLE_CLASS_INVALID`."

    Design: Corner/validations/referential_and_preemption_rules_59_to_65_reject_cross_entity_mismatches
    """
    plant = fx.setup_base_plant()
    asset = fx.create_asset(plant)
    delivered = fx.deliver_asset(plant, asset["id"])
    assert delivered["status"] == "RECEIVED", \
        f"precondition: asset must be RECEIVED, got {delivered['status']}"

    resp = api.submit_qc_report(
        asset["id"],
        fc.qc_report_payload(delivered["version"], plant["eng"]["id"]),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_OPERATOR_ROLE_CLASS_INVALID")


def test_guaranteed_spot_blocks_a_cut_in_without_the_flag(api):
    """The fiscal gate refuses the interruption rather than crediting silently.

    PRD §3.8: "Preemption here obeys the same fiscal gate as elsewhere: only spots whose order's `priority_class` is `PREEMPTIBLE` or `REMNANT` are eligible, and a `GUARANTEED` spot is preempted only when the activation carries `force_preempt_guaranteed` set to true, otherwise the activation is refused with `ERR_ORDER_NOT_PREEMPTIBLE`."

    Design: Corner/validations/referential_and_preemption_rules_59_to_65_reject_cross_entity_mismatches
    """
    rig = _guaranteed_cutin_rig()
    resp = api.activate_override(
        rig["override"]["id"],
        {"authorized_by_operator_id": rig["pd"]["id"], "override_mode": "CUT_IN"},
        rig["pd_headers"],
    )
    validate_error(resp, "ERR_ORDER_NOT_PREEMPTIBLE")


def test_forced_cut_in_preempts_the_guaranteed_spot_at_full_credit(api):
    """With the flag set the cut-in airs and the advertiser is made whole.

    PRD §3.7: "a `GUARANTEED` spot is preempted **only when the request carries `force_preempt_guaranteed` set to true**, in which case it accrues full credit."

    Design: Corner/validations/referential_and_preemption_rules_59_to_65_reject_cross_entity_mismatches
    """
    rig = _guaranteed_cutin_rig()
    activated = fx.activate_override(
        rig, rig["override"]["id"], "CUT_IN", force_preempt_guaranteed=True,
    )
    assert activated["state"] == "ACTIVE_CUTIN", \
        f"expected the cut-in to be on air, got state {activated['state']}"

    order = fx.read_order(rig["order"]["id"], rig["traffic_headers"])
    assert order["credited_spots"] == 1, \
        f"expected the guaranteed spot credited, got {order['credited_spots']}"
    assert order["credit_accrued_cents"] == 100000, \
        f"expected full credit of 100000 cents, got {order['credit_accrued_cents']}"


# ===========================================================================
# Conditionally required fields bind only their own branch
# ===========================================================================

def test_cut_in_request_needs_no_crawl_text(api):
    """The crawl text is asked for only when the requested mode is a crawl.

    PRD §3.8: "A `MasterControlOperator` or `ProgramDirector` requests one by naming the `channel_id` to be overridden, the `requested_by_operator_id` of the requesting operator, the `alert_class`, the `override_mode` wanted, the `requested_start_utc` at which the override is intended to begin, the `expected_duration_seconds` it is planned to run — at least 1 — and, when the mode is a crawl, the `crawl_text` itself."

    Design: Corner/validations/conditionally_required_fields_are_only_required_on_their_own_branch_and_blank_is_absent
    """
    plant = fx.setup_base_plant()
    payload = fc.create_override_payload(
        plant["ch1"]["id"], plant["mco"]["id"], "CUT_IN",
    )
    assert "crawl_text" not in payload, \
        "precondition: the cut-in request must carry no crawl text"

    created = validate_success(
        api.create_override(payload, plant["mco_headers"]), 201,
    )
    assert created["override_mode"] == "CUT_IN", \
        f"expected a cut-in request, got {created['override_mode']}"


def test_crawl_activation_without_crawl_text_is_refused(api):
    """The same field becomes mandatory once a crawl is what goes on air.

    PRD §3.8: "And a crawl activation, whether from `PENDING` or as a relaxation from a cut-in, requires a non-null `crawl_text`, otherwise `ERR_CRAWL_TEXT_REQUIRED`."

    Design: Corner/validations/conditionally_required_fields_are_only_required_on_their_own_branch_and_blank_is_absent
    """
    plant = fx.setup_base_plant()
    override = fx.request_override(plant, "CUT_IN")

    resp = api.activate_override(
        override["id"],
        {"authorized_by_operator_id": plant["pd"]["id"], "override_mode": "CRAWL"},
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_CRAWL_TEXT_REQUIRED")


def test_mitigation_without_a_code_is_refused(api):
    """Moving a fault to mitigated demands the code that mitigated it.

    PRD §3.3: "Mitigating a fault, whether from `ACKNOWLEDGED` or from `ESCALATED`, requires a `mitigation_code`; its absence yields `ERR_MITIGATION_CODE_REQUIRED`."

    Design: Corner/validations/conditionally_required_fields_are_only_required_on_their_own_branch_and_blank_is_absent
    """
    plant = fx.setup_base_plant()
    fault = fx.report_channel_fault(plant, "AUDIO_LOSS", "MAJOR", _T0)
    acknowledged = fx.advance_fault(plant, fault["id"], "ACKNOWLEDGED")
    assert acknowledged["state"] == "ACKNOWLEDGED", \
        f"precondition: fault must be ACKNOWLEDGED, got {acknowledged['state']}"

    resp = api.change_fault_state(
        fault["id"], {"target_state": "MITIGATED"}, plant["mco_headers"],
    )
    validate_error(resp, "ERR_MITIGATION_CODE_REQUIRED")


def test_mitigation_with_its_code_is_accepted_and_recorded(api):
    """Supplied on its own branch, the code is written to the fault.

    PRD §3.3: "The code is written to the fault, and when that code is `BARS_AND_TONE` and the channel's `air_status` is currently `ON_AIR`, the mitigation itself drives the channel from `ON_AIR` to `BARS_AND_TONE`, carrying that transition's own consequence — the currently playing item is truncated and an as-run truncation row is appended."

    Design: Corner/validations/conditionally_required_fields_are_only_required_on_their_own_branch_and_blank_is_absent
    """
    plant = fx.setup_base_plant()
    fault = fx.report_channel_fault(plant, "AUDIO_LOSS", "MAJOR", _T0)
    fx.advance_fault(plant, fault["id"], "ACKNOWLEDGED")

    mitigated = fx.advance_fault(
        plant, fault["id"], "MITIGATED", mitigation_code="SWITCH_TO_BACKUP",
    )
    assert mitigated["state"] == "MITIGATED", \
        f"expected MITIGATED, got {mitigated['state']}"
    assert mitigated["mitigation_code"] == "SWITCH_TO_BACKUP", \
        f"expected the code recorded, got {mitigated['mitigation_code']}"


def test_ingest_with_no_items_is_refused(api):
    """A broadcast day cannot be imported empty.

    PRD §3.5: "**At least one item must have been supplied**; an ingest with an empty `items` array is refused with `ERR_PLAYLIST_EMPTY_INGEST`."

    Design: Corner/validations/conditionally_required_fields_are_only_required_on_their_own_branch_and_blank_is_absent
    """
    plant = fx.setup_base_plant()
    resp = api.ingest_playlist(
        fc.ingest_playlist_payload(plant["ch1"]["id"], []),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_PLAYLIST_EMPTY_INGEST")


# ===========================================================================
# Inclusive thresholds: the exact value fires no rule
# ===========================================================================

def test_clock_advance_of_one_second_is_accepted(api):
    """Strictly forward means one second forward is enough.

    PRD §2.4: "A clock advance must move strictly forward: a request whose `current_utc` equals or precedes the present clock value is rejected with `ERR_CLOCK_NOT_MONOTONIC`."

    Design: Corner/validations/every_inclusive_threshold_accepts_its_exact_value_so_no_rule_may_fire_on_the_boundary
    """
    fx.setup_base_plant()
    validate_success(api.set_clock(_T0_PLUS_1, TEST_USERS["admin_headers"]))


def test_reduction_to_exactly_eighty_percent_files_nothing(api):
    """The regulatory threshold is strict, so the boundary creates no obligation.

    PRD §3.1: "The threshold is strict: a reduction to exactly 80 percent creates no filing obligation, while 79 percent does."

    Design: Corner/validations/every_inclusive_threshold_accepts_its_exact_value_so_no_rule_may_fire_on_the_boundary
    """
    plant = fx.setup_base_plant()
    reduced = fx.change_power_state(plant, "REDUCED_POWER", power_pct=80)
    assert reduced["current_power_pct"] == 80, \
        f"expected the observed power at 80, got {reduced['current_power_pct']}"

    notifications = fx.list_notifications(
        plant["transmitter"]["id"], plant["compliance_headers"],
    )
    assert notifications == [], \
        f"expected no filing obligation at exactly 80 percent, got {notifications}"


def test_cue_exactly_at_the_logical_clock_is_accepted(api):
    """An event stamped at the present instant is not in the future.

    PRD §3.6: "An `event_utc` exactly equal to the logical clock is accepted, and an `event_utc` exactly equal to the previous entry's `event_utc` is accepted."

    Design: Corner/validations/every_inclusive_threshold_accepts_its_exact_value_so_no_rule_may_fire_on_the_boundary
    """
    scn = fx.setup_on_air_playlist()
    validate_success(
        api.post_playout_event(
            scn["items"][0]["id"],
            {"event_kind": "CUE", "event_utc": "2026-08-01T11:59:00Z"},
            scn["mco_headers"],
        ),
        201,
    )

    entries = fx.list_as_run(scn["playlist"]["id"], scn["mco_headers"])
    assert as_run_kinds(entries) == ["CUE"], \
        f"expected the cue logged at the clock instant, got {as_run_kinds(entries)}"
