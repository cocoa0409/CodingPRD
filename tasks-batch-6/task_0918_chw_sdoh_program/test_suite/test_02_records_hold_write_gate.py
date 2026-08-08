"""The rung-4 records-hold write gate: what it pre-empts, what it exempts,
when it is skipped, and the five-link cascade that placing it fires."""

from test_helpers import (
    ApiErrorId,
    assert_offering_counters,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.constants import UNKNOWN_UUID
from test_helpers.test_users import SUPERVISOR, SUPERVISOR_ID, make_chw_headers


def test_records_hold_preempts_a_payload_domain_failure(api):
    """PRD §2.6: "The gate is evaluated at rung 4 of the ladder — after
    authentication, role authorization and path-id resolution, but **before**
    payload validation. The ordering is deliberate and observable: a request
    that is both malformed and aimed at a held patient returns
    `ERR_PATIENT_RECORDS_HOLD` (HTTP 409), not `ERR_VALIDATION`."
    PRD §3.6: "Under `INCREASE_GOOD` — think monthly grocery-budget dollars, or
    kept-appointment counts — `target_value` must be strictly greater than
    `baseline_value`."

    Design: Difficulty/priority_pair_validation_conflict/write_gate_rung4_preempts_payload_rung5
    """
    worker, patient, chw_headers = fx.program_with_patient(employee_code="W-009")
    fx.place_records_hold(patient["id"], "Consent withdrawn")

    response = api.create_goal(
        {
            "patient_id": patient["id"],
            "domain": "FOOD",
            "direction": "INCREASE_GOOD",
            "baseline_value": 10,
            "target_value": 5,
        },
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_PATIENT_RECORDS_HOLD.value, 409)
    assert response.status_code == 409


def test_the_same_malformed_goal_body_is_a_payload_failure_without_the_hold(api):
    """PRD §3.6: "Violating either constraint is `ERR_VALIDATION`."
    PRD §2.6: "The gate is evaluated at rung 4 of the ladder — after
    authentication, role authorization and path-id resolution, but **before**
    payload validation. The ordering is deliberate and observable: a request
    that is both malformed and aimed at a held patient returns
    `ERR_PATIENT_RECORDS_HOLD` (HTTP 409), not `ERR_VALIDATION`."

    Design: Difficulty/priority_pair_validation_conflict/write_gate_rung4_preempts_payload_rung5
    """
    worker, held, chw_headers = fx.program_with_patient(employee_code="W-009B")
    open_patient = fx.add_patient(
        chw_headers, mrn="MRN-090B", full_name="Ungated Twin"
    )
    fx.enroll_patient(open_patient["id"])
    fx.place_records_hold(held["id"], "Consent withdrawn")

    bad_body = {
        "domain": "FOOD",
        "direction": "INCREASE_GOOD",
        "baseline_value": 10,
        "target_value": 5,
    }

    gated = api.create_goal({**bad_body, "patient_id": held["id"]}, chw_headers)
    validate_error(gated, ApiErrorId.ERR_PATIENT_RECORDS_HOLD.value, 409)

    ungated = api.create_goal(
        {**bad_body, "patient_id": open_patient["id"]}, chw_headers
    )
    validate_error(ungated, ApiErrorId.ERR_VALIDATION.value, 400)

    _rows, meta = validate_paginated(
        api.list_goals(chw_headers, params={"patient_id": held["id"]})
    )
    assert meta["total_count"] == 0, "the gated request created no goal"
    assert fx.read_patient(held["id"])["gate_status"] == "RECORDS_HOLD", (
        "the refused request left the gate exactly where it was"
    )


def test_placing_a_hold_lapses_sent_referrals_and_releases_their_units(api):
    """PRD §3.1: "Second — caused by that first link — every referral belonging
    to this patient whose `status` is `SENT` transitions to `LAPSED` with
    `lapse_reason` set to `RECORDS_HOLD`."
    PRD §3.1: "Third, caused by each of those lapses, that referral's hold is
    released back to its offering: `allocated_units` falls by the referral's
    `units_requested`, `available_units` rises by the same amount,
    `released_units` rises by the same amount, and the offering's `version`
    increments by 1."

    Design: Difficulty/transitive_cascade/records_hold_depth_five_cascade_to_escalation_auto_resolution
    """
    scene = fx.exhausted_offering_with_escalation(employee_code="W-007")
    patient, offering, referral = scene["patient"], scene["offering"], scene["referral"]

    held = validate_success(
        api.records_hold(
            patient["id"],
            {"action": "PLACE", "reason": "Patient withdrew consent to share records"},
            SUPERVISOR,
        )
    )
    assert held["gate_status"] == "RECORDS_HOLD"
    assert held["gate_reason"] == "Patient withdrew consent to share records"

    lapsed = fx.read_referral(referral["id"])
    assert lapsed["status"] == "LAPSED", (
        f"a SENT referral of a newly held patient lapses, got {lapsed['status']}"
    )
    assert lapsed["lapse_reason"] == "RECORDS_HOLD", (
        f"the cascade stamps lapse_reason RECORDS_HOLD, got {lapsed['lapse_reason']}"
    )

    after = fx.read_offering(offering["id"])
    assert_offering_counters(
        after, available=1, allocated=0, delivered=0, released=1, expired=0, lifetime=1
    )
    assert after["capacity_total"] == 1


def test_the_released_hold_restores_the_offering_and_auto_resolves_its_escalation(api):
    """PRD §3.1: "Fourth, caused by the third link whenever that release lifts
    an offering's `available_units` from 0 to a positive number, the offering's
    `availability_state` flips from `EXHAUSTED` back to `AVAILABLE` and its
    `exhausted_since` is cleared to null."
    PRD §3.1: "Fifth, caused by the fourth, every escalation whose
    `source_flag` is `RESOURCE_EXHAUSTED` and whose `blocking_offering_id` names
    that offering, and whose `status` is any of `OPEN_TIER_1`, `OPEN_TIER_2` or
    `OPEN_TIER_3`, transitions to `RESOLVED` with `resolution_reason` set to
    `RESOURCE_RESTORED`."
    PRD §3.10: "There is also a system path to resolution that skips
    acknowledgement entirely: when an offering that had gone `EXHAUSTED` returns
    to `AVAILABLE`, every escalation with `source_flag` `RESOURCE_EXHAUSTED` and
    `blocking_offering_id` naming that offering is auto-resolved from
    `OPEN_TIER_1`, from `OPEN_TIER_2` or from `OPEN_TIER_3` alike, taking
    `resolution_reason` of `RESOURCE_RESTORED` and leaving
    `acknowledged_by_user_id` null."

    Design: Difficulty/transitive_cascade/records_hold_depth_five_cascade_to_escalation_auto_resolution
    """
    scene = fx.exhausted_offering_with_escalation(employee_code="W-007B")
    patient, offering = scene["patient"], scene["offering"]
    escalation = scene["escalation"]
    assert escalation is not None, (
        "driving available_units to 0 must open a RESOURCE_EXHAUSTED escalation"
    )
    assert escalation["source_flag"] == "RESOURCE_EXHAUSTED"
    assert escalation["blocking_offering_id"] == offering["id"]
    assert escalation["status"] == "OPEN_TIER_1"

    fx.place_records_hold(patient["id"], "Patient withdrew consent to share records")

    restored = fx.read_offering(offering["id"])
    assert restored["availability_state"] == "AVAILABLE", (
        "units returning above 0 flips the offering back to AVAILABLE"
    )
    assert restored["exhausted_since"] is None, (
        "exhausted_since is cleared when the offering becomes AVAILABLE again"
    )

    resolved = fx.read_escalation(escalation["id"])
    assert resolved["status"] == "RESOLVED", (
        f"the restored offering auto-resolves its escalation, got {resolved['status']}"
    )
    assert resolved["resolution_reason"] == "RESOURCE_RESTORED"
    assert resolved["acknowledged_by_user_id"] is None, (
        "the system resolution path skips acknowledgement entirely"
    )

    reread_patient = fx.read_patient(patient["id"])
    assert reread_patient["unfulfilled_referral_count"] == 1, (
        "one lapse charges the counter once, below the escalation threshold of 2"
    )


def test_gate_exempt_endpoints_still_operate_while_a_hold_is_in_force(api):
    """PRD §2.6: "Everything else proceeds normally even while a hold is in
    force. Specifically: every read endpoint without exception, because a hold
    restricts writes and never reads; placing or releasing the hold itself,
    under both the place and the release action, since otherwise a held patient
    could never be released; creating a patient, which cannot have a gated
    subject; cancelling a home visit, so an in-flight visit on a newly held
    patient can always be stood down; voiding an encounter, so corrections
    remain possible while a hold is in force; acknowledging and resolving
    escalations, so open escalations remain closeable; the three partner-side
    referral operations — responding, recording delivery and closing the loop —
    because the resource organization is a third party and is not bound by the
    provider's records hold; the three payer-side operations on an
    already-submitted claim — adjudication, appeal and appeal decision;
    reversing a grant charge line, which is a compensating action; running a
    system sweep, together with every cascade a sweep fires; the
    eligibility-check capability, which computes and stores nothing; and every
    endpoint with no patient subject at all — worker registration, screening
    instruments, resource organizations, offerings, eligibility criteria, grant
    awards, the logical clock and the program report."
    PRD §2.6: "Exactly nineteen operations are gated. When their resolved
    subject patient is on a records hold, each returns
    `ERR_PATIENT_RECORDS_HOLD`:"

    Design: Corner/validations/write_gate_exempt_endpoints_still_operate_under_records_hold
    """
    worker, patient, chw_headers = fx.program_with_patient(employee_code="C-048")
    visit = fx.schedule_visit(
        chw_headers, patient["id"], worker["id"],
        "2026-06-04T09:00:00Z", "2026-06-04T10:00:00Z",
    )
    escalation = fx.open_manual_escalation(
        chw_headers, patient["id"], "Food insecurity with a child in the home"
    )
    fx.place_records_hold(patient["id"], "Consent withdrawn")

    gated = api.create_goal(
        {
            "patient_id": patient["id"],
            "domain": "FOOD",
            "direction": "INCREASE_GOOD",
            "baseline_value": 1,
            "target_value": 5,
        },
        chw_headers,
    )
    validate_error(gated, ApiErrorId.ERR_PATIENT_RECORDS_HOLD.value, 409)

    cancelled = validate_success(api.cancel_home_visit(visit["id"], chw_headers))
    assert cancelled["scheduling_status"] == "CANCELLED", (
        "cancelling a home visit is exempt from the gate"
    )

    acknowledged = validate_success(
        api.acknowledge_escalation(escalation["id"], SUPERVISOR)
    )
    assert acknowledged["status"] == "ACKNOWLEDGED", (
        "acknowledging an escalation is exempt from the gate"
    )
    assert acknowledged["acknowledged_by_user_id"] == SUPERVISOR_ID

    assert fx.read_patient(patient["id"])["gate_status"] == "RECORDS_HOLD"
    _rows, meta = validate_paginated(
        api.list_goals(chw_headers, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0, "reads are never gated, and no goal was created"


def test_gate_is_skipped_when_the_body_patient_id_does_not_resolve(api):
    """PRD §2.6: "If step 2, 3 or 4 names an identifier that does not resolve to
    an existing patient, the rung is **skipped** rather than failed — evaluation
    falls through to rung 5. This is what keeps `ERR_VALIDATION` and the rung-6
    not-found errors reachable on malformed or dangling requests."
    PRD §2.5: "**Body-referenced existence** — every foreign key supplied in the
    request body resolves. A `patient_id` that does not resolve yields
    `ERR_PATIENT_NOT_FOUND` (404); every other body-supplied reference
    (`instrument_id`, `offering_id`, `opened_by_chw_id`, `assigned_chw_id`,
    `second_chw_id`, `chw_id`, `home_visit_id`, `resource_org_id`,
    `grant_award_id`, `encounter_id`) yields `ERR_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/validations/write_gate_skipped_when_body_patient_id_does_not_resolve
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    worker = fx.register_worker(employee_code="C-049")
    chw_headers = make_chw_headers(worker["id"])

    bad_enum = api.create_goal(
        {
            "patient_id": UNKNOWN_UUID,
            "domain": "NUTRITION",
            "direction": "INCREASE_GOOD",
            "baseline_value": 1,
            "target_value": 5,
        },
        chw_headers,
    )
    validate_error(bad_enum, ApiErrorId.ERR_VALIDATION.value, 400)

    dangling = api.create_goal(
        {
            "patient_id": UNKNOWN_UUID,
            "domain": "FOOD",
            "direction": "INCREASE_GOOD",
            "baseline_value": 1,
            "target_value": 5,
        },
        chw_headers,
    )
    validate_error(dangling, ApiErrorId.ERR_PATIENT_NOT_FOUND.value, 404)
