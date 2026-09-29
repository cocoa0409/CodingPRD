"""State-machine corners: initial states, terminal lockdown, refused transitions.

Every test in this file drives one published state machine to a corner the PRD
names explicitly — a fresh entity's initial state, a replayed transition, a
transition attempted from a terminal state, a precondition that is not yet met,
or a cascade that fires on a legal transition — and asserts the exact error
identifier the PRD's own prose pins for that endpoint (§2.8, §5).
"""
from datetime import datetime

from test_helpers import (
    AUDIT_CLOSER_ID,
    AUDIT_OPENER_ID,
    CURATOR_HEADERS,
    DIRECTOR_SECOND_ID,
    PERMIT_OFFICER_HEADERS,
    PLAN_APPROVER_ID,
    VET_HEADERS,
    VET_ID,
    VET_SECOND_HEADERS,
    VET_SECOND_ID,
    constants,
    factories,
    make_director_headers,
    shift,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_AUDIT_NOT_DUE,
    ERR_CLEARANCE_EXAMS_INSUFFICIENT,
    ERR_ENTITY_TERMINAL,
    ERR_INVALID_ACTION,
    ERR_INVALID_STATE,
    ERR_QUARANTINE_NOT_COMPLETE,
    ERR_ROUND_LIMIT_EXCEEDED,
    ERR_SOD_VIOLATION,
)

EPOCH = constants.CLOCK_EPOCH


def instant(value):
    """Parse an ISO 8601 UTC instant, with or without fractional seconds."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def same_instant(actual, expected):
    """Two ISO 8601 UTC strings denote the same instant."""
    return instant(actual) == instant(expected)


# ---------------------------------------------------------------------------
# Collection plan entry
# ---------------------------------------------------------------------------
def test_a_new_collection_plan_line_is_born_in_draft_with_no_approval_stamps(build, api):
    """Creating a plan line lands it in DRAFT with every approval field still null.

    PRD §3.4: "The entry's `status` begins at `DRAFT` and ends, if it ends, at `RETIRED`."
    PRD §3.4: "Approval stamps `approved_by_user_id` with the acting `X-User-ID` and
    `approved_at` with the logical clock"
    PRD §2.4: "`version`, an integer that starts at 1 on creation and increments by
    exactly one on every mutation of that resource."

    Design: Corner/state_machines/state_collection_plan_entry_starts_in_draft
    """
    plant = build.create_plant(design_habitat="COLD_MARINE")
    exhibit = build.create_exhibit(plant)
    species = build.create_species()

    payload = factories.collection_plan_entry_payload(
        exhibit["id"],
        species["id"],
        build.exhibit_version(exhibit["id"]),
        planned_count=2,
        sustainability_requirement="GREEN_ONLY",
    )
    entry = validate_success(api.create_collection_plan_entry(payload, CURATOR_HEADERS), 201)

    assert entry["status"] == "DRAFT", entry["status"]
    assert entry["approved_by_user_id"] is None, entry["approved_by_user_id"]
    assert entry["approved_at"] is None, entry["approved_at"]
    assert entry["superseded_by_entry_id"] is None, entry["superseded_by_entry_id"]
    assert entry["suspension_reason"] is None, entry["suspension_reason"]
    assert entry["planned_count"] == 2, entry["planned_count"]
    assert entry["sustainability_requirement"] == "GREEN_ONLY", entry["sustainability_requirement"]
    assert entry["version"] == 1, entry["version"]

    # §3.4: creation only retires a predecessor when the exhibit already has an
    # APPROVED line for the same species; there was none, so nothing was retired.
    retired, meta = validate_paginated(
        api.list_collection_plan_entries(CURATOR_HEADERS, {"status": "RETIRED"})
    )
    assert meta["total_count"] == 0, meta
    assert retired == [], retired

    stored = validate_success(api.get_collection_plan_entry(entry["id"], CURATOR_HEADERS))
    assert stored["status"] == "DRAFT", stored["status"]
    assert stored["approved_by_user_id"] is None, stored["approved_by_user_id"]
    assert stored["version"] == 1, stored["version"]


def test_replaying_approve_on_an_approved_plan_line_returns_invalid_state(build, api):
    """A second APPROVE is refused and does not re-stamp the first approver.

    PRD §3.4: "**Approve** takes a `DRAFT` entry to `APPROVED`."
    PRD §2.8: "The requested transition is declared from the target entity's current
    state — `ERR_INVALID_STATE` (409). Applies to plan-entry status actions"

    Design: Corner/state_machines/state_plan_entry_second_approve_returns_invalid_state
    """
    plant = build.create_plant(design_habitat="COLD_MARINE")
    exhibit = build.create_exhibit(plant)
    species = build.create_species()
    entry = build.create_plan_entry(exhibit, species, planned_count=2, sustainability_requirement="GREEN_ONLY")
    approved = build.plan_action(entry["id"], "APPROVE", headers=make_director_headers(PLAN_APPROVER_ID))

    assert approved["status"] == "APPROVED", approved["status"]
    assert approved["approved_by_user_id"] == PLAN_APPROVER_ID, approved["approved_by_user_id"]
    assert same_instant(approved["approved_at"], EPOCH), approved["approved_at"]
    assert approved["version"] == 2, approved["version"]

    response = api.plan_entry_status_action(
        entry["id"], {"action": "APPROVE"}, make_director_headers(DIRECTOR_SECOND_ID)
    )
    validate_error(response, ERR_INVALID_STATE, 409)

    # The refusal persists nothing: the first approver's anchor survives, and the
    # anchor is what the segregation-of-duties check at clearance compares (§2.11).
    stored = validate_success(api.get_collection_plan_entry(entry["id"], CURATOR_HEADERS))
    assert stored["status"] == "APPROVED", stored["status"]
    assert stored["approved_by_user_id"] == PLAN_APPROVER_ID, stored["approved_by_user_id"]
    assert same_instant(stored["approved_at"], EPOCH), stored["approved_at"]
    assert stored["version"] == 2, stored["version"]


def test_a_retired_plan_line_refuses_every_further_status_action(build, api):
    """From terminal RETIRED both RETIRE and REINSTATE return ERR_ENTITY_TERMINAL.

    PRD §3.4: "**Retire** takes an entry to the terminal `RETIRED` from `DRAFT`,
    `APPROVED` or `SUSPENDED` alike."
    PRD §2.8: "The target entity is not already in one of its terminal states —
    `ERR_ENTITY_TERMINAL` (409). Applies to plan-entry status actions ... This code
    distinguishes "terminal, nothing further is possible" from "wrong non-terminal
    state": a second mortality declaration on a `DECEASED` specimen is
    `ERR_ENTITY_TERMINAL`, not `ERR_INVALID_STATE`."

    Design: Corner/state_machines/state_plan_entry_retire_twice_returns_entity_terminal
    """
    plant = build.create_plant(design_habitat="COLD_MARINE")
    exhibit = build.create_exhibit(plant)
    species = build.create_species()
    entry = build.create_plan_entry(exhibit, species, planned_count=2, sustainability_requirement="GREEN_ONLY")
    retired = build.plan_action(entry["id"], "RETIRE", headers=make_director_headers(PLAN_APPROVER_ID))

    assert retired["status"] == "RETIRED", retired["status"]
    assert retired["version"] == 2, retired["version"]

    second_retire = api.plan_entry_status_action(
        entry["id"], {"action": "RETIRE"}, make_director_headers(PLAN_APPROVER_ID)
    )
    validate_error(second_retire, ERR_ENTITY_TERMINAL, 409)

    reinstate = api.plan_entry_status_action(
        entry["id"], {"action": "REINSTATE"}, make_director_headers(PLAN_APPROVER_ID)
    )
    validate_error(reinstate, ERR_ENTITY_TERMINAL, 409)

    stored = validate_success(api.get_collection_plan_entry(entry["id"], CURATOR_HEADERS))
    assert stored["status"] == "RETIRED", stored["status"]
    assert stored["version"] == 2, stored["version"]


# ---------------------------------------------------------------------------
# Quarantine reviews
# ---------------------------------------------------------------------------
def _quarantined_teleost(build):
    """A TELEOST specimen accessioned at the epoch, so a 30-day quarantine."""
    world = build.quarantined_specimen()
    case = world["quarantine_case"]
    assert case["status"] == "ACTIVE", case["status"]
    assert case["protocol_days"] == 30, case["protocol_days"]
    assert same_instant(case["projected_release_at"], shift(EPOCH, days=30)), case["projected_release_at"]
    return world


def test_quarantine_clearance_before_the_projected_release_instant_is_refused(build, api):
    """Both clean exams banked, but the duration gate still refuses an early CLEAR.

    PRD §3.6: "**`CLEAR`** moves an `ACTIVE` case to the terminal `CLEARED`. The
    logical clock must have reached `projected_release_at`, inclusive, else
    `ERR_QUARANTINE_NOT_COMPLETE`; `clearance_exam_count` must be at least 2, else
    `ERR_CLEARANCE_EXAMS_INSUFFICIENT`"

    Design: Corner/state_machines/state_quarantine_clear_before_projected_release_is_refused
    """
    world = _quarantined_teleost(build)
    specimen, case = world["specimen"], world["quarantine_case"]

    build.advance_to(shift(EPOCH, days=4))
    exams = [build.open_vet_case(specimen["id"], "PREVENTIVE_EXAM") for _ in range(2)]
    build.advance_to(shift(EPOCH, days=19))
    for exam in exams:
        build.close_vet_case(exam["id"], "RESOLVED", "NONE")

    banked = build.get_quarantine_case(case["id"])
    assert banked["clearance_exam_count"] == 2, banked["clearance_exam_count"]

    response = api.create_quarantine_review(case["id"], {"outcome": "CLEAR"}, VET_HEADERS)
    validate_error(response, ERR_QUARANTINE_NOT_COMPLETE, 409)

    unmoved = build.get_quarantine_case(case["id"])
    assert unmoved["status"] == "ACTIVE", unmoved["status"]
    assert unmoved["cleared_at"] is None, unmoved["cleared_at"]
    assert unmoved["cleared_by_user_id"] is None, unmoved["cleared_by_user_id"]
    assert unmoved["version"] == banked["version"], unmoved["version"]
    # The exam gate was satisfied, so only the duration gate can have refused it.
    assert unmoved["clearance_exam_count"] == 2, unmoved["clearance_exam_count"]
    assert same_instant(unmoved["projected_release_at"], shift(EPOCH, days=30)), unmoved["projected_release_at"]

    held = build.get_specimen(specimen["id"])
    assert held["disposition_status"] == "QUARANTINE", held["disposition_status"]


def test_quarantine_clearance_with_a_single_clean_exam_is_refused(build, api):
    """Past the release instant but one exam short, CLEAR fails on the exam gate.

    PRD §3.6: "`clearance_exam_count` must be at least 2, else
    `ERR_CLEARANCE_EXAMS_INSUFFICIENT`"

    Design: Corner/state_machines/state_quarantine_clear_with_a_single_exam_is_refused
    """
    world = _quarantined_teleost(build)
    specimen, case = world["specimen"], world["quarantine_case"]

    build.advance_to(shift(EPOCH, days=4))
    exam = build.open_vet_case(specimen["id"], "PREVENTIVE_EXAM")
    build.advance_to(shift(EPOCH, days=31))
    build.close_vet_case(exam["id"], "RESOLVED", "NONE")

    banked = build.get_quarantine_case(case["id"])
    assert banked["clearance_exam_count"] == 1, banked["clearance_exam_count"]
    # §2.8 rank 21 is already satisfied — the clock is past projected_release_at —
    # so the refusal below can only come from rank 22.
    assert instant(build.now) > instant(banked["projected_release_at"]), build.now

    response = api.create_quarantine_review(case["id"], {"outcome": "CLEAR"}, VET_HEADERS)
    validate_error(response, ERR_CLEARANCE_EXAMS_INSUFFICIENT, 409)

    unmoved = build.get_quarantine_case(case["id"])
    assert unmoved["status"] == "ACTIVE", unmoved["status"]
    assert unmoved["clearance_exam_count"] == 1, unmoved["clearance_exam_count"]
    assert unmoved["cleared_at"] is None, unmoved["cleared_at"]
    assert unmoved["version"] == banked["version"], unmoved["version"]

    held = build.get_specimen(specimen["id"])
    assert held["disposition_status"] == "QUARANTINE", held["disposition_status"]


def test_clearing_an_extended_quarantine_case_returns_invalid_action(build, api):
    """CLEAR is not a declared outcome from EXTENDED, so it is an invalid action.

    PRD §3.6: "Clearing is legal **only** from `ACTIVE`: an `EXTENDED` case must be
    resumed first, and a `CLEAR` outcome against it is `ERR_INVALID_ACTION`."
    PRD §2.8: "The supplied `action`, `outcome` or `decision` value is legal from the
    entity's current state — `ERR_INVALID_ACTION` (422) ... For example, a `CLEAR`
    outcome on an `EXTENDED` quarantine case is an invalid action, because the case
    must be resumed first"

    Design: Corner/state_machines/state_quarantine_clear_on_an_extended_case_returns_invalid_action
    """
    world = _quarantined_teleost(build)
    specimen, case = world["specimen"], world["quarantine_case"]

    build.advance_to(shift(EPOCH, days=4))
    exams = [build.open_vet_case(specimen["id"], "PREVENTIVE_EXAM") for _ in range(2)]
    build.advance_to(shift(EPOCH, days=31))
    for exam in exams:
        build.close_vet_case(exam["id"], "RESOLVED", "NONE")

    extended = build.review_quarantine(
        case["id"], "EXTEND", extension_days=10, reason="intermittent inappetence on day 30"
    )
    assert extended["status"] == "EXTENDED", extended["status"]
    assert extended["extension_count"] == 1, extended["extension_count"]
    assert extended["total_extension_days"] == 10, extended["total_extension_days"]
    # §3.6: projected_release_at is started_at plus (protocol_days + total_extension_days).
    assert same_instant(extended["projected_release_at"], shift(EPOCH, days=40)), extended["projected_release_at"]

    response = api.create_quarantine_review(case["id"], {"outcome": "CLEAR"}, VET_HEADERS)
    validate_error(response, ERR_INVALID_ACTION, 422)

    unmoved = build.get_quarantine_case(case["id"])
    assert unmoved["status"] == "EXTENDED", unmoved["status"]
    assert unmoved["extension_count"] == 1, unmoved["extension_count"]
    assert unmoved["total_extension_days"] == 10, unmoved["total_extension_days"]
    assert same_instant(unmoved["projected_release_at"], shift(EPOCH, days=40)), unmoved["projected_release_at"]
    assert unmoved["cleared_at"] is None, unmoved["cleared_at"]
    assert unmoved["version"] == extended["version"], unmoved["version"]

    held = build.get_specimen(specimen["id"])
    assert held["disposition_status"] == "QUARANTINE", held["disposition_status"]


# ---------------------------------------------------------------------------
# Life support estate
# ---------------------------------------------------------------------------
def test_a_failed_redundancy_test_takes_the_plant_offline_and_closes_its_exhibit(build, api):
    """FAIL drives OFFLINE and CLOSED without moving last_redundancy_test_at; PASS recovers.

    PRD §3.1: "A `FAIL` sets `last_redundancy_test_result` to `FAIL`, leaves
    `last_redundancy_test_at` **unchanged** — a failed test does not restart the
    redundancy interval — and takes the plant to `OFFLINE` from `NORMAL`, `WARNING` or
    `CRITICAL` alike; the plant's `redundancy_class` is irrelevant to this, so even a
    `TWO_N` plant goes offline on a single failed test. Every served exhibit then moves
    to `CLOSED` with `last_posture_reason` set to `LSS_OFFLINE`"

    Design: Corner/state_machines/state_redundancy_test_failure_takes_the_plant_offline_and_closes_the_exhibit
    """
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_class="N_PLUS_1")
    exhibit = build.create_exhibit(plant)
    assert exhibit["posture"] == "OPEN", exhibit["posture"]
    assert exhibit["version"] == 1, exhibit["version"]

    build.record_redundancy_test(plant["id"], "FAIL")

    offline = build.get_plant(plant["id"])
    assert offline["alarm_state"] == "OFFLINE", offline["alarm_state"]
    assert offline["last_redundancy_test_result"] == "FAIL", offline["last_redundancy_test_result"]
    assert offline["last_redundancy_test_at"] is None, offline["last_redundancy_test_at"]
    # §3.1: `water_quality_index` "is 100.00 while the plant has no readings at all".
    assert offline["water_quality_index"] == 100.00, offline["water_quality_index"]

    closed = build.get_exhibit(exhibit["id"])
    assert closed["posture"] == "CLOSED", closed["posture"]
    assert closed["last_posture_reason"] == "LSS_OFFLINE", closed["last_posture_reason"]
    assert closed["version"] == 2, closed["version"]

    build.record_redundancy_test(plant["id"], "PASS")

    # §3.1: "From `OFFLINE`, a `PASS` ... returns it to the band its water chemistry
    # actually justifies ... the plant has no readings at all, it returns to `NORMAL`".
    recovered = build.get_plant(plant["id"])
    assert recovered["alarm_state"] == "NORMAL", recovered["alarm_state"]
    assert recovered["last_redundancy_test_result"] == "PASS", recovered["last_redundancy_test_result"]
    assert same_instant(recovered["last_redundancy_test_at"], EPOCH), recovered["last_redundancy_test_at"]
    assert recovered["redundancy_overdue"] is False, recovered["redundancy_overdue"]

    reopened = build.get_exhibit(exhibit["id"])
    assert reopened["posture"] == "OPEN", reopened["posture"]
    assert reopened["last_posture_reason"] is None, reopened["last_posture_reason"]
    assert reopened["version"] == 3, reopened["version"]


# ---------------------------------------------------------------------------
# Clinical escalation
# ---------------------------------------------------------------------------
def test_a_critical_treatment_closure_pulls_the_specimen_off_its_exhibit(build, api):
    """MORTALITY_REFERRED escalates care, vacates the tank and opens no necropsy.

    PRD §3.7: "`MORTALITY_REFERRED` requires a `findings_severity` of `CRITICAL` and
    drives the **clinical-escalation coupling** in four links. First, `health_status`
    becomes `CRITICAL_CARE`, reachable from `UNDER_TREATMENT`. Second, if the
    specimen's `disposition_status` is `ON_EXHIBIT` it is pulled off: the disposition
    returns to `CLEARED`, `exhibit_id` becomes null and `holding_area` becomes
    `LAST_KNOWN_HOLDING`. Third, the vacated exhibit recomputes its ledger and its
    posture. ... No necropsy case is created by this outcome; a critical finding is an
    escalation of care, not a declaration of death."

    Design: Corner/state_machines/state_critical_treatment_closure_pulls_the_specimen_off_exhibit
    """
    world = build.specimen_on_exhibit()
    specimen, exhibit = world["specimen"], world["exhibit"]

    assert specimen["disposition_status"] == "ON_EXHIBIT", specimen["disposition_status"]
    assert specimen["health_status"] == "HEALTHY", specimen["health_status"]
    loaded = build.get_exhibit(exhibit["id"])
    assert loaded["occupied_bioload_units"] == specimen["bioload_units"], loaded["occupied_bioload_units"]

    treatment = build.open_vet_case(
        specimen["id"],
        "TREATMENT",
        treatment_start_at=build.now,
        withdrawal_days=10,
        diagnosis_code="BACT-DERM-02",
    )
    under_treatment = build.get_specimen(specimen["id"])
    assert under_treatment["health_status"] == "UNDER_TREATMENT", under_treatment["health_status"]

    closure = validate_success(
        api.close_veterinary_case(
            treatment["id"],
            {"outcome": "MORTALITY_REFERRED", "findings_severity": "CRITICAL"},
            VET_SECOND_HEADERS,
        )
    )
    assert closure["status"] == "CLOSED", closure["status"]
    assert closure["outcome"] == "MORTALITY_REFERRED", closure["outcome"]
    assert closure["findings_severity"] == "CRITICAL", closure["findings_severity"]
    assert closure["closed_by_user_id"] == VET_SECOND_ID, closure["closed_by_user_id"]

    escalated = build.get_specimen(specimen["id"])
    assert escalated["health_status"] == "CRITICAL_CARE", escalated["health_status"]
    assert escalated["disposition_status"] == "CLEARED", escalated["disposition_status"]
    assert escalated["exhibit_id"] is None, escalated["exhibit_id"]
    assert escalated["holding_area"] == "LAST_KNOWN_HOLDING", escalated["holding_area"]

    vacated = build.get_exhibit(exhibit["id"])
    assert vacated["occupied_bioload_units"] == 0.00, vacated["occupied_bioload_units"]
    assert vacated["bioload_utilization_pct"] == 0.00, vacated["bioload_utilization_pct"]
    assert vacated["posture"] == "OPEN", vacated["posture"]
    assert vacated["last_posture_reason"] is None, vacated["last_posture_reason"]

    necropsies, meta = validate_paginated(
        api.list_specimen_veterinary_cases(specimen["id"], VET_HEADERS, {"case_type": "NECROPSY"})
    )
    assert meta["total_count"] == 0, meta
    assert necropsies == [], necropsies


def test_the_officer_who_opened_the_necropsy_may_not_finalise_it(build, api):
    """The mortality-created necropsy refuses its own opener, then accepts a second officer.

    PRD §3.7: "`NECROPSY_FINALIZED` requires a `case_type` of `NECROPSY`, a `status` of
    `OPEN`, a non-null `findings_severity`, and an acting `X-User-ID` different from the
    case's `opened_by_user_id`, else `ERR_SOD_VIOLATION`. It moves `health_status` from
    `DECEASED_PENDING_NECROPSY` to the terminal `NECROPSY_COMPLETE`."
    PRD §2.11: "The veterinary officer who opened a necropsy case may not be the one
    who finalises it."

    Design: Corner/state_machines/state_necropsy_closure_by_the_opening_officer_returns_sod_violation
    """
    world = build.quarantined_specimen()
    specimen, quarantine_case = world["specimen"], world["quarantine_case"]

    build.declare_mortality(specimen["id"], cause_note="found deceased on morning round")

    cases, meta = validate_paginated(
        api.list_specimen_veterinary_cases(specimen["id"], VET_HEADERS, {"case_type": "NECROPSY"})
    )
    assert meta["total_count"] == 1, meta
    necropsy = cases[0]
    assert necropsy["status"] == "OPEN", necropsy["status"]
    assert necropsy["opened_by_user_id"] == VET_ID, necropsy["opened_by_user_id"]

    self_signed = api.close_veterinary_case(
        necropsy["id"], {"outcome": "NECROPSY_FINALIZED", "findings_severity": "MAJOR"}, VET_HEADERS
    )
    validate_error(self_signed, ERR_SOD_VIOLATION, 409)

    still_open = validate_success(api.get_veterinary_case(necropsy["id"], VET_HEADERS))
    assert still_open["status"] == "OPEN", still_open["status"]
    assert still_open["closed_by_user_id"] is None, still_open["closed_by_user_id"]
    assert still_open["version"] == necropsy["version"], still_open["version"]

    finalised = validate_success(
        api.close_veterinary_case(
            necropsy["id"],
            {"outcome": "NECROPSY_FINALIZED", "findings_severity": "MAJOR"},
            VET_SECOND_HEADERS,
        )
    )
    assert finalised["status"] == "CLOSED", finalised["status"]
    assert finalised["outcome"] == "NECROPSY_FINALIZED", finalised["outcome"]
    assert finalised["opened_by_user_id"] == VET_ID, finalised["opened_by_user_id"]
    assert finalised["closed_by_user_id"] == VET_SECOND_ID, finalised["closed_by_user_id"]

    dead = build.get_specimen(specimen["id"])
    assert dead["health_status"] == "NECROPSY_COMPLETE", dead["health_status"]
    assert dead["disposition_status"] == "DECEASED", dead["disposition_status"]

    # §3.7: the mortality cascade fails the open quarantine case with MORTALITY.
    failed = build.get_quarantine_case(quarantine_case["id"])
    assert failed["status"] == "FAILED", failed["status"]
    assert failed["failure_reason"] == "MORTALITY", failed["failure_reason"]


# ---------------------------------------------------------------------------
# Outbound transfer negotiation
# ---------------------------------------------------------------------------
def test_a_third_counter_on_a_transfer_exceeds_the_negotiation_ceiling(build, api):
    """The SUBMITTED/COUNTERED loop is bounded at two counters.

    PRD §3.8: "`COUNTER` belongs to the partner liaison. It moves a `SUBMITTED` request
    to `COUNTERED`, requires the acting `X-User-ID` to equal the request's
    `receiving_institution_id`, requires `negotiation_round` plus 1 to be no greater
    than 2 (else `ERR_ROUND_LIMIT_EXCEEDED`) and a non-empty `counter_conditions`
    array, stores those conditions, increments `negotiation_round`"

    Design: Corner/state_machines/state_transfer_third_counter_exceeds_the_negotiation_ceiling
    """
    world = build.cleared_specimen()
    specimen = world["specimen"]
    institution = build.create_institution(
        accreditation_status="ACCREDITED", welfare_audit_score=88.00, last_audit_at=shift(EPOCH, days=-90)
    )
    liaison = build.liaison_headers(institution["id"])

    transfer = build.draft_transfer(
        specimen["id"],
        institution["id"],
        shift(build.now, days=31),
        welfare_conditions=["WATER_CHEMISTRY_MATCH", "TRANSPORT_OXYGEN_PLAN"],
    )
    assert transfer["negotiation_round"] == 0, transfer["negotiation_round"]
    build.submit_transfer(transfer["id"])

    first = build.decide_transfer(
        transfer["id"], "COUNTER", headers=liaison, counter_conditions=["QUARANTINE_ON_ARRIVAL"]
    )
    assert first["status"] == "COUNTERED", first["status"]
    assert first["negotiation_round"] == 1, first["negotiation_round"]
    build.submit_transfer(
        transfer["id"],
        welfare_conditions=["WATER_CHEMISTRY_MATCH", "TRANSPORT_OXYGEN_PLAN", "QUARANTINE_ON_ARRIVAL"],
    )

    second = build.decide_transfer(
        transfer["id"], "COUNTER", headers=liaison, counter_conditions=["DIET_TRANSITION_PLAN"]
    )
    assert second["negotiation_round"] == 2, second["negotiation_round"]
    settled = ["WATER_CHEMISTRY_MATCH", "TRANSPORT_OXYGEN_PLAN", "QUARANTINE_ON_ARRIVAL", "DIET_TRANSITION_PLAN"]
    resubmitted = build.submit_transfer(transfer["id"], welfare_conditions=settled)
    assert resubmitted["status"] == "SUBMITTED", resubmitted["status"]

    third = api.decide_transfer_request(
        transfer["id"], {"decision": "COUNTER", "counter_conditions": ["NO_COMMERCIAL_RESALE"]}, liaison
    )
    validate_error(third, ERR_ROUND_LIMIT_EXCEEDED, 409)

    unmoved = validate_success(api.get_transfer_request(transfer["id"], PERMIT_OFFICER_HEADERS))
    assert unmoved["status"] == "SUBMITTED", unmoved["status"]
    assert unmoved["negotiation_round"] == 2, unmoved["negotiation_round"]
    assert unmoved["counter_conditions"] == ["DIET_TRANSITION_PLAN"], unmoved["counter_conditions"]
    assert unmoved["welfare_conditions"] == settled, unmoved["welfare_conditions"]
    assert unmoved["version"] == resubmitted["version"], unmoved["version"]

    # §3.8: the first submission moved the animal and recorded where it came from.
    offered = build.get_specimen(specimen["id"])
    assert offered["disposition_status"] == "TRANSFER_PENDING", offered["disposition_status"]
    assert offered["pre_transfer_disposition"] == "CLEARED", offered["pre_transfer_disposition"]


# ---------------------------------------------------------------------------
# Accreditation audits
# ---------------------------------------------------------------------------
def test_starting_an_audit_before_it_is_due_returns_audit_not_due(build, api):
    """START before scheduled_for is refused and no scoring step runs.

    PRD §3.9: "`START` moves a `SCHEDULED` audit to `IN_PROGRESS` and requires the
    logical clock to have reached `scheduled_for`, else `ERR_AUDIT_NOT_DUE`."
    PRD §3.9: "It is born `SCHEDULED` with an empty `readiness_score`, empty
    `domain_subscores`, an empty `blocking_finding_count`, no `opened_by_user_id`, no
    `closed_by_user_id`, no `started_at`, no `closed_at` and no `determination_note`."

    Design: Corner/state_machines/state_audit_start_before_scheduled_for_returns_audit_not_due
    """
    audit = build.schedule_audit(scheduled_for=shift(EPOCH, days=45), scope="FULL")
    assert audit["status"] == "SCHEDULED", audit["status"]
    assert instant(build.now) < instant(audit["scheduled_for"]), audit["scheduled_for"]

    response = api.progress_accreditation_audit(
        audit["id"], {"action": "START"}, make_director_headers(AUDIT_OPENER_ID)
    )
    validate_error(response, ERR_AUDIT_NOT_DUE, 409)

    unmoved = validate_success(api.get_accreditation_audit(audit["id"], make_director_headers(AUDIT_OPENER_ID)))
    assert unmoved["status"] == "SCHEDULED", unmoved["status"]
    assert unmoved["readiness_score"] is None, unmoved["readiness_score"]
    assert not unmoved["domain_subscores"], unmoved["domain_subscores"]
    assert not unmoved["blocking_finding_count"], unmoved["blocking_finding_count"]
    assert unmoved["opened_by_user_id"] is None, unmoved["opened_by_user_id"]
    assert unmoved["started_at"] is None, unmoved["started_at"]
    assert unmoved["version"] == 1, unmoved["version"]


def test_an_audit_of_an_empty_collection_scores_a_hundred_and_passes_for_a_second_director(build, api):
    """Every empty-set fallback is 100.00, and only a second director may close.

    PRD §3.9: "`LIFE_SUPPORT` is the mean over every plant ... with no plants at all it
    is 100.00. `ANIMAL_HEALTH` is the mean `welfare_score` over specimens whose
    `disposition_status` is `CLEARED` or `ON_EXHIBIT` and whose `welfare_score` is
    non-null; with no such specimens it is 100.00."
    PRD §3.9: "`CLOSE` moves an `IN_PROGRESS` audit to one of three determinations and
    requires the acting `X-User-ID` to differ from `opened_by_user_id`, else
    `ERR_SOD_VIOLATION`. ... the audit becomes the terminal `PASSED` when
    `readiness_score` is at least 85.00 **and** `blocking_finding_count` is 0"

    Design: Corner/state_machines/state_audit_close_on_an_empty_collection_passes_and_enforces_sod
    """
    audit = build.schedule_audit(scheduled_for=EPOCH, scope="FULL")
    started = build.progress_audit(audit["id"], "START", headers=make_director_headers(AUDIT_OPENER_ID))

    assert started["status"] == "IN_PROGRESS", started["status"]
    assert started["domain_subscores"] == {
        "LIFE_SUPPORT": 100.00,
        "ANIMAL_HEALTH": 100.00,
        "RECORDS": 100.00,
        "PERMITS": 100.00,
        "PUBLIC_SAFETY": 100.00,
    }, started["domain_subscores"]
    assert started["readiness_score"] == 100.00, started["readiness_score"]
    assert started["blocking_finding_count"] == 0, started["blocking_finding_count"]
    assert started["opened_by_user_id"] == AUDIT_OPENER_ID, started["opened_by_user_id"]
    assert same_instant(started["started_at"], EPOCH), started["started_at"]

    self_signed = api.progress_accreditation_audit(
        audit["id"],
        {"action": "CLOSE", "determination_note": "self-signed determination attempt"},
        make_director_headers(AUDIT_OPENER_ID),
    )
    validate_error(self_signed, ERR_SOD_VIOLATION, 409)

    still_open = validate_success(
        api.get_accreditation_audit(audit["id"], make_director_headers(AUDIT_OPENER_ID))
    )
    assert still_open["status"] == "IN_PROGRESS", still_open["status"]
    assert still_open["closed_by_user_id"] is None, still_open["closed_by_user_id"]
    assert still_open["determination_note"] is None, still_open["determination_note"]
    assert still_open["version"] == started["version"], still_open["version"]

    closed = validate_success(
        api.progress_accreditation_audit(
            audit["id"],
            {"action": "CLOSE", "determination_note": "no findings on an empty collection"},
            make_director_headers(AUDIT_CLOSER_ID),
        )
    )
    assert closed["status"] == "PASSED", closed["status"]
    assert closed["closed_by_user_id"] == AUDIT_CLOSER_ID, closed["closed_by_user_id"]
    assert same_instant(closed["closed_at"], EPOCH), closed["closed_at"]
    assert closed["determination_note"] == "no findings on an empty collection", closed["determination_note"]
    assert closed["readiness_score"] == 100.00, closed["readiness_score"]
    assert closed["blocking_finding_count"] == 0, closed["blocking_finding_count"]
