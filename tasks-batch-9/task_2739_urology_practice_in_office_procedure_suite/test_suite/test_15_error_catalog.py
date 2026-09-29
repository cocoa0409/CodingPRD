"""
The error catalogue: one identifier per violated rule, and the state left behind.

Every refusal in this contract carries its own identifier and its own HTTP
status, and a caller is expected to be able to tell the failures apart without
reading the message text. The tests here walk the catalogue rung by rung: the
twelve not-found codes and the order in which references resolve, the natural
keys that may not collide, the guards on opening and closing a sterile-
processing stage log, the prophylaxis eligibility refusals, the two room guards
at commit time, the five specimen chain-of-custody guards, the two scope
guards at assignment, the consignment device guards on both sides of check-in,
and the pelvic-health visit ledger. Each refusal is paired with a read-back
proving the rejected request changed nothing, and — wherever the contract
declares the same operation succeeds under different circumstances — with the
neighbouring success that proves the refusal was attributable to the rule under
test and not to some accident of the setup.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ANTIBIOTIC_CONTRAINDICATED,
    ERR_ANTIBIOTIC_ORDER_NOT_FOUND,
    ERR_CASE_NOT_FOUND,
    ERR_DEVICE_ALREADY_RESERVED,
    ERR_DEVICE_NOT_RESERVED,
    ERR_DUPLICATE_CONTAINER_LABEL,
    ERR_DUPLICATE_PROCEDURE_TYPE_CODE,
    ERR_DUPLICATE_ROOM_NAME,
    ERR_DUPLICATE_SCOPE_SERIAL,
    ERR_HLD_CERTIFICATION_REQUIRED,
    ERR_INVALID_NOTIFICATION_TRANSITION,
    ERR_INVALID_REFERRAL_TRANSITION,
    ERR_INVALID_REPROCESSING_TRANSITION,
    ERR_INVALID_SPECIMEN_TRANSITION,
    ERR_LOT_NOT_FOUND,
    ERR_NO_ELIGIBLE_ANTIBIOTIC,
    ERR_PATIENT_NOT_FOUND,
    ERR_PROCEDURE_TYPE_NOT_FOUND,
    ERR_PROVIDER_NOT_FOUND,
    ERR_RECALL_NOT_FOUND,
    ERR_REFERRAL_NOT_FOUND,
    ERR_REPROCESSING_LOG_ALREADY_OPEN,
    ERR_REPROCESSING_LOG_NOT_FOUND,
    ERR_REPROCESSING_STAGE_OUT_OF_ORDER,
    ERR_ROOM_CLOSED,
    ERR_ROOM_NOT_FOUND,
    ERR_ROOM_TYPE_MISMATCH,
    ERR_SCOPE_LEAK_TEST_DUE,
    ERR_SCOPE_NOT_AVAILABLE,
    ERR_SPECIMEN_NOT_EXPECTED,
    ERR_SPECIMEN_NOT_FOUND,
    ERR_SPECIMEN_TRANSIT_EXPIRED,
    ERR_THERAPY_START_WINDOW_MISSED,
    ERR_VISIT_ALLOCATION_EXHAUSTED,
)
from test_helpers.assertions import (
    assert_fields,
    assert_lot_counters,
    assert_null_fields,
    assert_readiness,
    assert_specimen_dimensions,
    assert_version_unchanged,
    assert_visit_counters,
)
from test_helpers.constants import (
    AGENT_AUTO,
    AGENT_CEFAZOLIN,
    AGENT_TMP_SMX,
    ALLERGY_CEPHALOSPORIN,
    ALLERGY_SULFA,
    BASIS_PROTOCOL_ANCHORED,
    CASE_COMPLETED,
    CASE_DRAFT,
    CASE_IN_ROOM,
    CASE_SCHEDULED,
    CHAIN_ACCESSIONED,
    CHAIN_COLLECTED,
    CHAIN_RESULTED,
    CHANNEL_PHONE,
    CLEANUP_HIGH,
    CLEANUP_LOW,
    CLEARANCE_PENDING_PREP,
    CONDITION_INTACT,
    DECISION_ACCEPT,
    DEVICE_CLASS_BIOPSY_NEEDLE,
    DEVICE_STATE_NONE,
    DEVICE_STATE_RESERVED,
    GATE_DEVICE_NOT_RESERVED,
    LOG_CLOSED,
    LOG_OPEN,
    NOTIFY_NOT_REQUIRED,
    NOTIFY_OUTCOME_REACHED,
    NOTIFY_PENDING,
    OUTCOME_FAIL,
    OUTCOME_PASS,
    PROGRAM_BIOFEEDBACK,
    PROGRAM_PELVIC_FLOOR_PT,
    PROTOCOL_BLADDER_CANCER,
    RECALL_SCHEDULED_DUE,
    REFERRAL_ACCEPTED,
    REFERRAL_COMPLETED,
    REFERRAL_REQUESTED,
    RESULT_BENIGN,
    RESULT_MALIGNANT,
    ROLE_TYPE_SCHEDULER,
    ROLE_TYPE_TECH,
    ROLE_TYPE_UROLOGIST,
    ROOM_STATUS_CLOSED,
    ROOM_STATUS_OPEN,
    ROOM_TYPE_CYSTO_SUITE,
    ROOM_TYPE_IMAGING_BAY,
    ROUTE_IV,
    SCOPE_IN_USE,
    SCOPE_QUARANTINED,
    SCOPE_SOILED,
    SPECIMEN_BLADDER_WASHING,
    SPECIMEN_PROSTATE_CORE,
    STAGE_HIGH_LEVEL_DISINFECT,
    STAGE_MANUAL_CLEAN,
    STAGE_PRECLEAN,
    TIER_LOW,
    TYPE_CYSTOSCOPY,
    TYPE_OFFICE_ULTRASOUND,
    TYPE_PROSTATE_BIOPSY,
    VISIT_ACTION_LOG,
    VISIT_ACTION_VOID_LAST,
)
from test_helpers.test_users import (
    make_scheduler_headers,
    make_sterile_processing_tech_headers,
)

# ─── Instance one: the not-found catalogue and reference resolution order ────

UNKNOWN_PROVIDER_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_ROOM_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_TYPE_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_CASE_ID = "00000000-0000-4000-8000-000000000004"
UNKNOWN_LOG_ID = "00000000-0000-4000-8000-000000000005"
UNKNOWN_ORDER_ID = "00000000-0000-4000-8000-000000000006"
UNKNOWN_SPECIMEN_ID = "00000000-0000-4000-8000-000000000007"
UNKNOWN_RECALL_ID = "00000000-0000-4000-8000-000000000008"
UNKNOWN_REFERRAL_ID = "00000000-0000-4000-8000-000000000009"
UNKNOWN_LOT_ID = "00000000-0000-4000-8000-00000000000a"

UNKNOWN_PATIENT_FK = "00000000-0000-4000-8000-0000000000b1"
UNKNOWN_TYPE_FK = "00000000-0000-4000-8000-0000000000b2"
UNKNOWN_ROOM_FK = "00000000-0000-4000-8000-0000000000b3"
UNKNOWN_PROVIDER_FK = "00000000-0000-4000-8000-0000000000b4"


def test_single_resource_reads_report_each_entitys_own_not_found_code(api, admin_headers):
    """PRD §2.8: "The error is the not-found code of the first path segment that
    fails to resolve, chosen from `ERR_PATIENT_NOT_FOUND`,
    `ERR_PROVIDER_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`,
    `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_SCOPE_NOT_FOUND`,
    `ERR_REPROCESSING_LOG_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
    `ERR_RECALL_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_LOT_NOT_FOUND` or
    `ERR_ANTIBIOTIC_ORDER_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/err_not_found_catalog_every_path_parameter
    """
    # The database is empty, so every identifier below is unresolvable. Each read
    # must answer with the code belonging to *its own* entity: ten reads, ten
    # distinct identifiers, all of them HTTP 404 (checked by validate_error
    # against the registered status of each code).
    probes = [
        (api.get_provider(UNKNOWN_PROVIDER_ID, admin_headers), ERR_PROVIDER_NOT_FOUND),
        (api.get_procedure_room(UNKNOWN_ROOM_ID, admin_headers), ERR_ROOM_NOT_FOUND),
        (
            api.get_procedure_type(UNKNOWN_TYPE_ID, admin_headers),
            ERR_PROCEDURE_TYPE_NOT_FOUND,
        ),
        (api.get_procedure_case(UNKNOWN_CASE_ID, admin_headers), ERR_CASE_NOT_FOUND),
        (
            api.get_reprocessing_log(UNKNOWN_LOG_ID, admin_headers),
            ERR_REPROCESSING_LOG_NOT_FOUND,
        ),
        (
            api.get_antibiotic_order(UNKNOWN_ORDER_ID, admin_headers),
            ERR_ANTIBIOTIC_ORDER_NOT_FOUND,
        ),
        (api.get_specimen(UNKNOWN_SPECIMEN_ID, admin_headers), ERR_SPECIMEN_NOT_FOUND),
        (
            api.get_surveillance_recall(UNKNOWN_RECALL_ID, admin_headers),
            ERR_RECALL_NOT_FOUND,
        ),
        (
            api.get_pelvic_health_referral(UNKNOWN_REFERRAL_ID, admin_headers),
            ERR_REFERRAL_NOT_FOUND,
        ),
        (api.get_consignment_lot(UNKNOWN_LOT_ID, admin_headers), ERR_LOT_NOT_FOUND),
    ]

    reported = []
    for response, expected_error_id in probes:
        reported.append(validate_error(response, expected_error_id)["error_id"])

    assert len(set(reported)) == len(reported), (
        "each entity owns its own not-found identifier, so the ten reads must "
        f"report ten different codes, got {reported}"
    )


def test_case_draft_reports_the_first_declared_unresolvable_reference(api):
    """PRD §3.2: "Those four references are resolved in exactly the order
    listed, so a payload naming both a non-existent patient and a non-existent
    room reports `ERR_PATIENT_NOT_FOUND`."

    Design: Corner/errors/err_not_found_catalog_every_path_parameter
    """
    # One legal actor and nothing else: the scheduler exists so identity
    # resolution passes and the request reaches the reference-resolution rung.
    scheduler = fx.create_provider(api, ROLE_TYPE_SCHEDULER, full_name="Sam Reyes")

    response = api.create_procedure_case(
        f.procedure_case_payload(
            patient_id=UNKNOWN_PATIENT_FK,
            procedure_type_id=UNKNOWN_TYPE_FK,
            room_id=UNKNOWN_ROOM_FK,
            primary_provider_id=UNKNOWN_PROVIDER_FK,
            scheduled_start_at="2026-09-14T09:00:00Z",
        ),
        make_scheduler_headers(scheduler["id"]),
    )

    # All four foreign keys are unresolvable at once. The answer is fixed by the
    # declared order of the fields, not by whichever lookup runs first.
    validate_error(response, ERR_PATIENT_NOT_FOUND)


# ─── Instance two: the three practice-wide natural keys ──────────────────────


def test_second_procedure_type_with_the_same_code_is_rejected(api, admin_headers):
    """PRD §3.1: "A procedure type carries a `code` that must be unique and must
    be one of `CYSTOSCOPY`, `URODYNAMICS`, `PROSTATE_BIOPSY` or
    `OFFICE_ULTRASOUND`, a duplicate raising
    `ERR_DUPLICATE_PROCEDURE_TYPE_CODE`."

    Design: Corner/errors/err_duplicate_natural_keys_rejected
    """
    fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        required_prep_codes=[],
    )

    # Every other field differs — a longer procedure, a lighter cleanup class, a
    # different room type — so only the repeated code can be the cause.
    response = api.create_procedure_type(
        f.procedure_type_payload(
            code=TYPE_CYSTOSCOPY,
            base_minutes=45,
            cleanup_class=CLEANUP_LOW,
            allowed_room_type="URODYNAMICS_LAB",
            required_prep_codes=[],
        ),
        admin_headers,
    )
    validate_error(response, ERR_DUPLICATE_PROCEDURE_TYPE_CODE)

    rows, meta = validate_paginated(api.list_procedure_types(admin_headers))
    assert meta["total_count"] == 1, (
        "the rejected definition must leave exactly one procedure type behind, "
        f"got total_count {meta['total_count']}"
    )
    assert_fields(
        rows[0],
        code=TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
    )


def test_second_room_with_the_same_name_is_rejected(api, admin_headers):
    """PRD §3.1: "Procedure rooms are commissioned with a `name` that must be
    unique across the suite — a collision is `ERR_DUPLICATE_ROOM_NAME` — and a
    `room_type` of `CYSTO_SUITE`, `URODYNAMICS_LAB` or `IMAGING_BAY`."

    Design: Corner/errors/err_duplicate_natural_keys_rejected
    """
    fx.create_room(api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10)

    response = api.create_procedure_room(
        f.procedure_room_payload(
            name="Cysto A", room_type=ROOM_TYPE_IMAGING_BAY, turnover_minutes=25
        ),
        admin_headers,
    )
    validate_error(response, ERR_DUPLICATE_ROOM_NAME)

    rows, meta = validate_paginated(api.list_procedure_rooms(admin_headers))
    assert meta["total_count"] == 1, (
        "the rejected commissioning must leave exactly one room behind, got "
        f"total_count {meta['total_count']}"
    )
    # The surviving row is the original: the losing payload's room type and
    # turnover allowance were not merged into it.
    assert_fields(
        rows[0],
        name="Cysto A",
        room_type=ROOM_TYPE_CYSTO_SUITE,
        turnover_minutes=10,
        room_status=ROOM_STATUS_OPEN,
    )


def test_second_scope_with_the_same_serial_number_is_rejected(api, admin_headers):
    """PRD §3.1: "Flexible cystoscopes enter the sterile-processing registry
    with a `serial_number` unique across the inventory (a collision being
    `ERR_DUPLICATE_SCOPE_SERIAL`), a `scope_model` designation, and a
    `channel_count` of at least 1 recording how many working channels a
    technician must clean by hand."

    Design: Corner/errors/err_duplicate_natural_keys_rejected
    """
    tech = fx.create_provider(api, ROLE_TYPE_TECH, full_name="Omar Diaz")
    tech_headers = make_sterile_processing_tech_headers(tech["id"])
    fx.create_scope(
        api, tech, serial_number="SN-9001", scope_model="FlexCysto 200", channel_count=2
    )

    response = api.create_scope_asset(
        f.scope_asset_payload(
            serial_number="SN-9001", scope_model="RigidCysto 40", channel_count=1
        ),
        tech_headers,
    )
    validate_error(response, ERR_DUPLICATE_SCOPE_SERIAL)

    rows, meta = validate_paginated(api.list_scope_assets(admin_headers))
    assert meta["total_count"] == 1, (
        "the rejected registration must leave exactly one scope behind, got "
        f"total_count {meta['total_count']}"
    )
    assert_fields(
        rows[0],
        serial_number="SN-9001",
        scope_model="FlexCysto 200",
        channel_count=2,
    )


# ─── Instance three: the guards on opening a stage log ───────────────────────

REPROCESSING_CLOCK = "2026-09-14T09:00:00Z"


def _build_soiled_scope_without_logs(api):
    """
    A cystoscope that has just come out of a patient case, so it is `SOILED`
    with no stage log of any kind behind it, plus a second technician whose
    ``hld_certified`` is false — the practice's newest recruit.

    A soiled scope with no history is the state in which all three open-time
    guards are reachable: the contract lets `PRECLEAN` be opened on it, so the
    stage-order rung passes for that stage and fails for any later one.
    """
    practice = fx.build_simple_practice(
        api,
        TYPE_CYSTOSCOPY,
        ROOM_TYPE_CYSTO_SUITE,
        type_kwargs={
            "base_minutes": 20,
            "cleanup_class": CLEANUP_HIGH,
            "requires_scope": True,
        },
        room_kwargs={"turnover_minutes": 10},
    )
    roster = practice["roster"]
    fx.set_clock(api, REPROCESSING_CLOCK, roster.admin_headers)
    scope = fx.build_ready_scope(
        api,
        roster,
        serial_number="SN-9002",
        scope_model="FlexCysto 200",
        channel_count=2,
    )
    case = fx.schedule_new_case(
        api,
        roster,
        practice["patient"],
        practice["procedure_type"],
        practice["room"],
        REPROCESSING_CLOCK,
    )
    fx.assign_scope(api, roster, case["id"], scope)
    fx.clear_case(api, roster, case["id"])
    fx.check_in_case(api, roster, case["id"])
    fx.complete_case(api, roster, case["id"])

    soiled = fx.read_scope(api, roster, scope["id"])
    assert_fields(soiled, status=SCOPE_SOILED, leak_test_required=False)
    _, log_meta = validate_paginated(api.list_reprocessing_logs(roster.admin_headers))
    assert log_meta["total_count"] == 0, (
        "the scope must carry no reprocessing history at all before the probes, "
        f"got total_count {log_meta['total_count']}"
    )

    uncertified = fx.create_provider(api, ROLE_TYPE_TECH, full_name="Rue Bell")
    assert_fields(uncertified, hld_certified=False)
    return roster, soiled, uncertified


def test_disinfect_log_opened_by_an_uncertified_technician_is_rejected(api):
    """PRD §3.5: "Only one log may be open per scope at a time — a second
    concurrent open is refused with `ERR_REPROCESSING_LOG_ALREADY_OPEN` — and a
    `HIGH_LEVEL_DISINFECT` log may only be opened where the performing
    technician's `hld_certified` is true, otherwise
    `ERR_HLD_CERTIFICATION_REQUIRED`."
    PRD §2.8: "A `HIGH_LEVEL_DISINFECT` stage may only be performed by a
    Provider whose `hld_certified` is true, and only attested by another Provider
    whose `hld_certified` is true. Otherwise `ERR_HLD_CERTIFICATION_REQUIRED`,
    HTTP 422."

    Design: Corner/errors/err_reprocessing_log_open_guards_rejected
    """
    roster, scope, uncertified = _build_soiled_scope_without_logs(api)

    # Disinfection is not the admissible stage for this scope either, so two
    # rungs of the ladder are unmet at once: priority 53 (certification) and
    # priority 56 (stage order). The lower-numbered rule is the one reported.
    response = api.create_reprocessing_log(
        f.reprocessing_log_payload(
            scope_asset_id=scope["id"],
            performed_by_provider_id=uncertified["id"],
            stage=STAGE_HIGH_LEVEL_DISINFECT,
        ),
        make_sterile_processing_tech_headers(uncertified["id"]),
    )

    validate_error(response, ERR_HLD_CERTIFICATION_REQUIRED)
    _, meta = validate_paginated(api.list_reprocessing_logs(roster.admin_headers))
    assert meta["total_count"] == 0, (
        "a refused open must not persist a log, got total_count "
        f"{meta['total_count']}"
    )


def test_manual_clean_as_the_first_stage_of_a_cycle_is_rejected(api):
    """PRD §3.5: "The five stages run in the fixed sequence `PRECLEAN`,
    `LEAK_TEST`, `MANUAL_CLEAN`, `HIGH_LEVEL_DISINFECT`, `DRY_STORE`, and a newly
    opened log's `stage` must be the immediate successor of the scope's last
    closed passing stage."
    PRD §3.5: "Two standing exceptions bend that rule where the business needs
    it: `LEAK_TEST` may always be opened whenever `leak_test_required` is true,
    and `PRECLEAN` may always be opened on a `SOILED` scope."

    Design: Corner/errors/err_reprocessing_log_open_guards_rejected
    """
    roster, scope, uncertified = _build_soiled_scope_without_logs(api)

    # The scope has no closed passing stage, and neither standing exception
    # covers MANUAL_CLEAN: the scope owes no leak test and the exception for a
    # soiled scope names PRECLEAN only.
    response = api.create_reprocessing_log(
        f.reprocessing_log_payload(
            scope_asset_id=scope["id"],
            performed_by_provider_id=uncertified["id"],
            stage=STAGE_MANUAL_CLEAN,
        ),
        make_sterile_processing_tech_headers(uncertified["id"]),
    )

    validate_error(response, ERR_REPROCESSING_STAGE_OUT_OF_ORDER)


def test_second_open_log_on_one_scope_is_rejected(api):
    """PRD §3.5: "Only one log may be open per scope at a time — a second
    concurrent open is refused with `ERR_REPROCESSING_LOG_ALREADY_OPEN` — and a
    `HIGH_LEVEL_DISINFECT` log may only be opened where the performing
    technician's `hld_certified` is true, otherwise
    `ERR_HLD_CERTIFICATION_REQUIRED`."
    PRD §3.5: "The new log is created with `log_status` `OPEN`, `started_at` at
    the logical clock instant, `outcome` null and `attested_by_provider_id`
    null."

    Design: Corner/errors/err_reprocessing_log_open_guards_rejected
    """
    roster, scope, uncertified = _build_soiled_scope_without_logs(api)

    # A precleaning log on a soiled scope is exactly what the contract allows,
    # and certification does not bind on this stage, so the first open succeeds.
    opened = validate_success(
        api.create_reprocessing_log(
            f.reprocessing_log_payload(
                scope_asset_id=scope["id"],
                performed_by_provider_id=uncertified["id"],
                stage=STAGE_PRECLEAN,
            ),
            make_sterile_processing_tech_headers(uncertified["id"]),
        ),
        201,
    )
    assert_fields(
        opened,
        scope_asset_id=scope["id"],
        stage=STAGE_PRECLEAN,
        log_status=LOG_OPEN,
        performed_by_provider_id=uncertified["id"],
    )
    assert_null_fields(opened, "outcome", "completed_at", "attested_by_provider_id")

    # The second open names the same admissible stage, so the stage-order rung
    # passes and the one-open-log rung is the rule that speaks.
    response = api.create_reprocessing_log(
        f.reprocessing_log_payload(
            scope_asset_id=scope["id"],
            performed_by_provider_id=roster.tech["id"],
            stage=STAGE_PRECLEAN,
        ),
        roster.tech_headers,
    )
    validate_error(response, ERR_REPROCESSING_LOG_ALREADY_OPEN)

    rows, meta = validate_paginated(api.list_reprocessing_logs(roster.admin_headers))
    assert meta["total_count"] == 1, (
        "the refused second open must leave the single open log behind, got "
        f"total_count {meta['total_count']}"
    )
    assert_fields(rows[0], id=opened["id"], log_status=LOG_OPEN)


# ─── Instance four: prophylaxis eligibility refusals ─────────────────────────

ANTIBIOTIC_CLOCK = "2026-09-14T07:00:00Z"


def _build_prophylaxis_stage(api):
    """
    Two patients whose renal function and allergies pull the formulary in
    opposite directions, and two procedure types — one that demands prophylaxis
    and one that has no protocol ranking at all — with a draft case for each
    combination the probes need. Ordering carries no calendar precondition, so
    the cases stay drafts.
    """
    roster = fx.build_roster(api)
    room = fx.create_room(api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10)
    biopsy_type = fx.create_procedure_type(
        api,
        TYPE_PROSTATE_BIOPSY,
        base_minutes=30,
        cleanup_class=CLEANUP_LOW,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_antibiotic=True,
        required_prep_codes=[],
    )
    ultrasound_type = fx.create_procedure_type(
        api,
        TYPE_OFFICE_ULTRASOUND,
        base_minutes=15,
        cleanup_class=CLEANUP_LOW,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        required_prep_codes=[],
    )
    patient_sulfa = fx.create_patient(
        api,
        roster.urologist,
        mrn="MRN-5050",
        full_name="Sana Ilk",
        date_of_birth="1966-06-06",
        egfr=62,
        antibiotic_allergy_class=ALLERGY_SULFA,
    )
    patient_renal = fx.create_patient(
        api,
        roster.urologist,
        mrn="MRN-5051",
        full_name="Cato Renn",
        date_of_birth="1949-09-19",
        egfr=20,
        antibiotic_allergy_class=ALLERGY_CEPHALOSPORIN,
    )
    fx.set_clock(api, ANTIBIOTIC_CLOCK, roster.admin_headers)
    cases = {
        "sulfa_biopsy": fx.draft_case(
            api, roster, patient_sulfa, biopsy_type, room, "2026-09-14T14:00:00Z"
        ),
        "renal_biopsy": fx.draft_case(
            api, roster, patient_renal, biopsy_type, room, "2026-09-14T16:00:00Z"
        ),
        "ultrasound": fx.draft_case(
            api, roster, patient_sulfa, ultrasound_type, room, "2026-09-14T18:00:00Z"
        ),
    }
    return roster, cases


def _order_antibiotic(api, roster, case_id, requested_agent):
    return api.create_antibiotic_order(
        f.antibiotic_order_payload(
            case_id=case_id,
            ordered_by_provider_id=roster.urologist["id"],
            requested_agent=requested_agent,
        ),
        roster.urologist_headers,
    )


def test_explicit_agent_in_the_patients_allergy_class_is_rejected(api):
    """PRD §3.4: "When `requested_agent` names a specific drug, that drug must
    itself be in the eligible pool; if it is not — because its class matches the
    patient's allergy, because the patient's renal function is below the agent's
    floor, or because the case's procedure type has no ranking that includes it —
    the order is refused with `ERR_ANTIBIOTIC_CONTRAINDICATED`."
    PRD §3.4: "`TMP_SMX` belongs to `SULFA`, needs at least 30, has a base dose
    of 160 milligrams and is `ORAL`."

    Design: Corner/errors/err_antibiotic_eligibility_rejected
    """
    roster, cases = _build_prophylaxis_stage(api)

    # The patient's egfr of 62 clears the drug's floor of 30 and the biopsy
    # ranking does include TMP_SMX, so the allergy class is the only failure.
    response = _order_antibiotic(api, roster, cases["sulfa_biopsy"]["id"], AGENT_TMP_SMX)

    validate_error(response, ERR_ANTIBIOTIC_CONTRAINDICATED)
    _, meta = validate_paginated(api.list_antibiotic_orders(roster.admin_headers))
    assert meta["total_count"] == 0, (
        "a refused order must not be persisted, got total_count "
        f"{meta['total_count']}"
    )


def test_auto_order_against_an_empty_eligible_pool_is_rejected(api):
    """PRD §3.4: "When `requested_agent` is `AUTO` and the eligible pool is
    empty, the order is refused with `ERR_NO_ELIGIBLE_ANTIBIOTIC`; this is also
    what happens to every `AUTO` order placed against a case whose procedure type
    does not require antibiotics."
    PRD §3.4: "An agent is **eligible** for a given order when all three of the
    following hold: its drug class is different from the patient's
    `antibiotic_allergy_class`; the patient's `egfr` is greater than or equal to
    the agent's minimum; and the agent appears in the protocol ranking that
    applies to the case's procedure type."

    Design: Corner/errors/err_antibiotic_eligibility_rejected
    """
    roster, cases = _build_prophylaxis_stage(api)

    # At an egfr of 20 the two oral agents (floor 30) and gentamicin (floor 60)
    # all drop out, and cefazolin is the patient's own allergy class: the pool is
    # empty although the procedure type does demand prophylaxis.
    response = _order_antibiotic(api, roster, cases["renal_biopsy"]["id"], AGENT_AUTO)

    validate_error(response, ERR_NO_ELIGIBLE_ANTIBIOTIC)
    _, meta = validate_paginated(api.list_antibiotic_orders(roster.admin_headers))
    assert meta["total_count"] == 0, (
        "a refused order must not be persisted, got total_count "
        f"{meta['total_count']}"
    )


def test_auto_order_on_a_type_that_needs_no_prophylaxis_is_rejected(api):
    """PRD §3.4: "A procedure type whose `requires_antibiotic` is false has no
    ranking at all, so its eligible pool is empty by construction."
    PRD §3.4: "When `requested_agent` is `AUTO` and the eligible pool is empty,
    the order is refused with `ERR_NO_ELIGIBLE_ANTIBIOTIC`; this is also what
    happens to every `AUTO` order placed against a case whose procedure type does
    not require antibiotics."

    Design: Corner/errors/err_antibiotic_eligibility_rejected
    """
    roster, cases = _build_prophylaxis_stage(api)

    # This is the same patient who is perfectly eligible for cefazolin on the
    # biopsy case: the emptiness here is structural, not clinical.
    response = _order_antibiotic(api, roster, cases["ultrasound"]["id"], AGENT_AUTO)

    validate_error(response, ERR_NO_ELIGIBLE_ANTIBIOTIC)


def test_auto_order_still_resolves_cefazolin_for_the_sulfa_allergic_patient(api):
    """PRD §3.4: "The joint first place in the prostate-biopsy ranking exists
    precisely to exercise that tie-break: for a patient with no relevant allergy
    the resolved `agent` is `CEFAZOLIN`, because `CEFAZOLIN` sorts before
    `CIPROFLOXACIN`; for a patient whose `antibiotic_allergy_class` is
    `CEPHALOSPORIN`, cefazolin drops out of the pool and `CIPROFLOXACIN` is
    chosen instead."
    PRD §3.4: "`CEFAZOLIN` belongs to `CEPHALOSPORIN`, needs at least 15, has a
    base dose of 1000 milligrams and is given `IV`."

    Design: Corner/errors/err_antibiotic_eligibility_rejected
    """
    roster, cases = _build_prophylaxis_stage(api)
    case_id = cases["sulfa_biopsy"]["id"]

    # The explicit request is refused ...
    validate_error(
        _order_antibiotic(api, roster, case_id, AGENT_TMP_SMX),
        ERR_ANTIBIOTIC_CONTRAINDICATED,
    )

    # ... and the very same case then accepts an AUTO order, which proves the
    # refusal was specific to the drug named and not to the case or the patient.
    order = validate_success(
        _order_antibiotic(api, roster, case_id, AGENT_AUTO), 201
    )
    assert_fields(
        order,
        case_id=case_id,
        agent=AGENT_CEFAZOLIN,
        dose_mg=1000,
        route=ROUTE_IV,
    )
    assert_null_fields(order, "administered_at")

    _, meta = validate_paginated(api.list_antibiotic_orders(roster.admin_headers))
    assert meta["total_count"] == 1, (
        "exactly one of the two orders may survive, got total_count "
        f"{meta['total_count']}"
    )


# ─── Instance five: the two room guards at commit time ───────────────────────

ROOM_GUARD_CLOCK = "2026-09-14T07:00:00Z"


def _build_two_room_stage(api):
    """
    Two rooms that fail the commit for two different reasons: a cystoscopy suite
    of exactly the right type that has been closed, and a fully accredited
    imaging bay of the wrong type. The operating urologist carries a valid
    ultrasound accreditation and the imaging bay's own accreditation runs to
    2027, so neither accreditation rung can pre-empt the type mismatch.
    """
    roster = fx.build_roster(api)
    accredited_urologist = fx.create_provider(
        api,
        ROLE_TYPE_UROLOGIST,
        full_name="Dr Ada Nour",
        ultrasound_accreditation_expires_on="2027-12-31",
    )
    cysto_room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    imaging_room = fx.create_room(
        api,
        ROOM_TYPE_IMAGING_BAY,
        name="Imaging 1",
        turnover_minutes=10,
        accreditation_body="ACR",
        accreditation_expires_on="2027-12-31",
    )
    procedure_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        required_prep_codes=[],
    )
    patient = fx.create_patient(
        api,
        roster.urologist,
        mrn="MRN-5052",
        full_name="Ilse Braun",
        date_of_birth="1961-01-21",
        egfr=66,
    )
    fx.set_clock(api, ROOM_GUARD_CLOCK, roster.admin_headers)
    cysto_case = fx.draft_case(
        api,
        roster,
        patient,
        procedure_type,
        cysto_room,
        "2026-09-14T09:00:00Z",
        provider=accredited_urologist,
    )
    imaging_case = fx.draft_case(
        api,
        roster,
        patient,
        procedure_type,
        imaging_room,
        "2026-09-14T13:00:00Z",
        provider=accredited_urologist,
    )
    # Drafting occupies nothing and does not look at the room's standing, so the
    # suite can be closed after its case is already on the books.
    closed_room = validate_success(
        api.update_procedure_room(
            cysto_room["id"],
            f.procedure_room_update_payload(room_status=ROOM_STATUS_CLOSED),
            roster.admin_headers,
        )
    )
    assert_fields(closed_room, room_status=ROOM_STATUS_CLOSED)
    return roster, closed_room, imaging_room, cysto_case, imaging_case


def test_committing_a_case_into_a_closed_room_is_rejected(api):
    """PRD §3.3: "The room's `room_status` must be `OPEN`, or the request is
    refused with `ERR_ROOM_CLOSED`."
    PRD §3.1: "Each room also exposes `occupied_block_count`, a derived count of
    the cases naming that room whose `schedule_status` is `SCHEDULED`, `IN_ROOM`
    or `COMPLETED`; it initialises to 0."

    Design: Corner/errors/err_room_state_and_type_guards_rejected
    """
    roster, closed_room, _, cysto_case, _ = _build_two_room_stage(api)

    # The room's type is exactly the one this procedure demands, and the version
    # carried is the room's current one, so neither the type rung nor the
    # optimistic-concurrency rung can account for the refusal.
    response = api.schedule_case(
        cysto_case["id"],
        f.schedule_payload(closed_room["version"]),
        roster.scheduler_headers,
    )
    validate_error(response, ERR_ROOM_CLOSED)

    case_after = fx.read_case(api, roster, cysto_case["id"])
    assert_fields(
        case_after,
        schedule_status=CASE_DRAFT,
        clearance_status=CLEARANCE_PENDING_PREP,
    )
    room_after = fx.read_room(api, roster, closed_room["id"])
    assert_fields(
        room_after, room_status=ROOM_STATUS_CLOSED, occupied_block_count=0
    )
    assert_version_unchanged(closed_room, room_after)


def test_committing_a_case_into_a_room_of_the_wrong_type_is_rejected(api):
    """PRD §3.3: "The room's `room_type` must equal the procedure type's
    `allowed_room_type`, or the request is refused with
    `ERR_ROOM_TYPE_MISMATCH`."
    PRD §3.1: "It carries an `allowed_room_type` of `CYSTO_SUITE`,
    `URODYNAMICS_LAB` or `IMAGING_BAY`, and that is the only room type into which
    cases of this procedure may ever be booked."

    Design: Corner/errors/err_room_state_and_type_guards_rejected
    """
    roster, _, imaging_room, _, imaging_case = _build_two_room_stage(api)

    # The imaging bay is OPEN and in accreditation, and its urologist is
    # accredited too, so the mismatch is the only rule left to fail.
    response = api.schedule_case(
        imaging_case["id"],
        f.schedule_payload(imaging_room["version"]),
        roster.scheduler_headers,
    )
    validate_error(response, ERR_ROOM_TYPE_MISMATCH)

    case_after = fx.read_case(api, roster, imaging_case["id"])
    assert_fields(case_after, schedule_status=CASE_DRAFT)
    room_after = fx.read_room(api, roster, imaging_room["id"])
    assert_fields(
        room_after, room_status=ROOM_STATUS_OPEN, occupied_block_count=0
    )
    assert_version_unchanged(imaging_room, room_after)


# ─── Instance six: the five specimen chain-of-custody guards ─────────────────

SPECIMEN_CLOCK = "2026-09-14T09:00:00Z"


def _build_specimen_case(api, bring_into_room):
    """
    A cystoscopy that is expected to produce a container, standing on the
    calendar at exactly the logical clock instant. When ``bring_into_room`` is
    true the case is cleared and checked in, which is the state the contract
    requires before a container may be labelled.
    """
    practice = fx.build_simple_practice(
        api,
        TYPE_CYSTOSCOPY,
        ROOM_TYPE_CYSTO_SUITE,
        type_kwargs={
            "base_minutes": 20,
            "cleanup_class": CLEANUP_HIGH,
            "requires_specimen": True,
            "required_prep_codes": [],
        },
        room_kwargs={"name": "Cysto A", "turnover_minutes": 10},
        patient_kwargs={
            "mrn": "MRN-5060",
            "full_name": "Nils Aro",
            "date_of_birth": "1958-03-03",
            "egfr": 71,
        },
    )
    roster = practice["roster"]
    fx.set_clock(api, SPECIMEN_CLOCK, roster.admin_headers)
    case = fx.schedule_new_case(
        api,
        roster,
        practice["patient"],
        practice["procedure_type"],
        practice["room"],
        SPECIMEN_CLOCK,
    )
    assert_fields(case, schedule_status=CASE_SCHEDULED)
    if bring_into_room:
        fx.clear_case(api, roster, case["id"])
        case = fx.check_in_case(api, roster, case["id"])
        assert_fields(case, schedule_status=CASE_IN_ROOM)
    return roster, practice["patient"], case


def _collect_container(api, roster, case_id, container_label, specimen_type, site_code):
    return api.create_specimen(
        f.specimen_payload(
            case_id=case_id,
            collected_by_provider_id=roster.nurse["id"],
            container_label=container_label,
            specimen_type=specimen_type,
            site_code=site_code,
        ),
        roster.nurse_headers,
    )


def _collected_specimen(api):
    """The stage of instance six from the first accepted container onwards."""
    roster, patient, case = _build_specimen_case(api, bring_into_room=True)
    specimen = validate_success(
        _collect_container(
            api,
            roster,
            case["id"],
            "CUP-1",
            SPECIMEN_BLADDER_WASHING,
            "BLADDER-DOME",
        ),
        201,
    )
    return roster, patient, case, specimen


def test_collecting_a_container_before_the_patient_is_in_the_room_is_rejected(api):
    """PRD §3.8: "Collection is only permitted where the case's procedure type
    has `requires_specimen` true and the case's `schedule_status` is `IN_ROOM` or
    `COMPLETED`; anything else is refused with `ERR_SPECIMEN_NOT_EXPECTED`."

    Design: Corner/errors/err_specimen_chain_guards_rejected
    """
    roster, _, case = _build_specimen_case(api, bring_into_room=False)

    # The procedure type does expect a container; it is the case's own schedule
    # dimension, still merely SCHEDULED, that refuses the collection.
    response = _collect_container(
        api, roster, case["id"], "CUP-1", SPECIMEN_BLADDER_WASHING, "BLADDER-DOME"
    )

    validate_error(response, ERR_SPECIMEN_NOT_EXPECTED)
    _, meta = validate_paginated(
        api.list_specimens(roster.admin_headers, case_id=case["id"])
    )
    assert meta["total_count"] == 0, (
        "a refused collection must not create a specimen row, got total_count "
        f"{meta['total_count']}"
    )


def test_reusing_a_container_label_within_one_case_is_rejected(api):
    """PRD §3.8: "The `container_label` must be unique among the specimens
    sharing that same `case_id`, though the same label may legitimately reappear
    on a different case; a within-case collision is refused with
    `ERR_DUPLICATE_CONTAINER_LABEL`."
    PRD §3.8: "The new specimen records `collected_at` at the logical clock
    instant, `chain_status` `COLLECTED`, `notification_status` `NOT_REQUIRED` and
    `notification_attempt_count` 0, with `accession_number`, `received_at`,
    `condition_on_receipt`, `pathology_result`, `result_at` and
    `escalation_due_at` all null."

    Design: Corner/errors/err_specimen_chain_guards_rejected
    """
    roster, _, case, specimen = _collected_specimen(api)
    assert_fields(
        specimen,
        case_id=case["id"],
        container_label="CUP-1",
        specimen_type=SPECIMEN_BLADDER_WASHING,
        site_code="BLADDER-DOME",
        collected_at="2026-09-14T09:00:00.000Z",
        chain_status=CHAIN_COLLECTED,
        notification_status=NOTIFY_NOT_REQUIRED,
        notification_attempt_count=0,
    )
    assert_null_fields(
        specimen,
        "accession_number",
        "received_at",
        "condition_on_receipt",
        "pathology_result",
        "result_at",
        "escalation_due_at",
    )

    # A different tissue type and a different anatomic site, but the same label
    # written on the pot: the label alone decides.
    response = _collect_container(
        api, roster, case["id"], "CUP-1", SPECIMEN_PROSTATE_CORE, "LEFT-BASE"
    )
    validate_error(response, ERR_DUPLICATE_CONTAINER_LABEL)

    rows, meta = validate_paginated(
        api.list_specimens(roster.admin_headers, case_id=case["id"])
    )
    assert meta["total_count"] == 1, (
        "the rejected collection must leave the one accepted container behind, "
        f"got total_count {meta['total_count']}"
    )
    assert_fields(rows[0], id=specimen["id"], specimen_type=SPECIMEN_BLADDER_WASHING)


def test_accession_more_than_a_day_after_collection_is_rejected(api):
    """PRD §3.8: "Both branches share the same preconditions: the specimen's
    `chain_status` must still be `COLLECTED`, or the request is refused with
    `ERR_INVALID_SPECIMEN_TRANSITION`; and transit must be sound, meaning
    `received_at` is not earlier than `collected_at` and no more than 24 hours
    after it, or the request is refused with `ERR_SPECIMEN_TRANSIT_EXPIRED`."
    PRD §3.8: "An `INTACT` container simply advances `chain_status` from
    `COLLECTED` to `ACCESSIONED` and does nothing else."

    Design: Corner/errors/err_specimen_chain_guards_rejected
    """
    roster, _, _, specimen = _collected_specimen(api)

    # Collected at 09:00 on the 14th; this arrival is 25 hours later, one hour
    # past the transit allowance.
    late = api.accession_specimen(
        specimen["id"],
        f.accession_payload(
            received_at="2026-09-15T10:00:00Z",
            accession_number="ACC-7001",
            condition_on_receipt=CONDITION_INTACT,
        ),
        roster.pathologist_headers,
    )
    validate_error(late, ERR_SPECIMEN_TRANSIT_EXPIRED)

    unchanged = fx.read_specimen(api, roster, specimen["id"])
    assert_specimen_dimensions(unchanged, CHAIN_COLLECTED, NOTIFY_NOT_REQUIRED)
    assert_null_fields(unchanged, "accession_number", "received_at")

    # The same container, the same laboratory, three hours after collection: the
    # refusal was about transit time and nothing else.
    in_time = validate_success(
        api.accession_specimen(
            specimen["id"],
            f.accession_payload(
                received_at="2026-09-14T12:00:00Z",
                accession_number="ACC-7001",
                condition_on_receipt=CONDITION_INTACT,
            ),
            roster.pathologist_headers,
        )
    )
    assert_fields(
        in_time,
        chain_status=CHAIN_ACCESSIONED,
        accession_number="ACC-7001",
        received_at="2026-09-14T12:00:00.000Z",
        condition_on_receipt=CONDITION_INTACT,
        notification_status=NOTIFY_NOT_REQUIRED,
    )


def test_notification_attempt_while_no_conversation_is_open_is_rejected(api):
    """PRD §3.8: "Attempts are accepted only while the notification dimension is
    `PENDING`, `ATTEMPTED` or `ESCALATED`; an attempt against a specimen whose
    `notification_status` is `NOT_REQUIRED`, `ACKNOWLEDGED` or `FAILED` is
    refused with `ERR_INVALID_NOTIFICATION_TRANSITION`."
    PRD §3.8: "Either outcome increments `notification_attempt_count` by 1."

    Design: Corner/errors/err_specimen_chain_guards_rejected
    """
    roster, _, _, specimen = _collected_specimen(api)
    accessioned = validate_success(
        api.accession_specimen(
            specimen["id"],
            f.accession_payload(
                received_at="2026-09-14T12:00:00Z",
                accession_number="ACC-7001",
                condition_on_receipt=CONDITION_INTACT,
            ),
            roster.pathologist_headers,
        )
    )
    # An intact container leaves the notification dimension shut: there is
    # nothing to tell the patient yet.
    assert_specimen_dimensions(accessioned, CHAIN_ACCESSIONED, NOTIFY_NOT_REQUIRED)

    response = api.record_notification_attempt(
        specimen["id"],
        f.notification_attempt_payload(
            outcome=NOTIFY_OUTCOME_REACHED, channel=CHANNEL_PHONE
        ),
        roster.pathologist_headers,
    )
    validate_error(response, ERR_INVALID_NOTIFICATION_TRANSITION)

    after = fx.read_specimen(api, roster, specimen["id"])
    assert_fields(
        after,
        notification_status=NOTIFY_NOT_REQUIRED,
        notification_attempt_count=0,
    )
    assert_null_fields(after, "escalation_due_at")


def test_second_result_on_a_resulted_specimen_is_rejected(api):
    """PRD §3.8: "Filing the pathology result is likewise the
    `PathologyLiaison`'s exclusive act, takes a single `pathology_result` of
    `BENIGN`, `ATYPICAL`, `MALIGNANT` or `INSUFFICIENT`, and requires the
    specimen's `chain_status` to be `ACCESSIONED`; filing against any other chain
    state is refused with `ERR_INVALID_SPECIMEN_TRANSITION`."
    PRD §3.8: "The first hop records the result on the specimen:
    `pathology_result` is stored, `result_at` is set to the logical clock instant,
    `chain_status` advances from `ACCESSIONED` to `RESULTED`,
    `notification_status` moves from `NOT_REQUIRED` to `PENDING` with
    `notification_attempt_count` still at 0, and `escalation_due_at` is
    computed."

    Design: Corner/errors/err_specimen_chain_guards_rejected
    """
    roster, patient, _, specimen = _collected_specimen(api)
    validate_success(
        api.accession_specimen(
            specimen["id"],
            f.accession_payload(
                received_at="2026-09-14T12:00:00Z",
                accession_number="ACC-7001",
                condition_on_receipt=CONDITION_INTACT,
            ),
            roster.pathologist_headers,
        )
    )

    resulted = validate_success(
        api.result_specimen(
            specimen["id"], f.result_payload(RESULT_BENIGN), roster.pathologist_headers
        )
    )
    # A benign grade allows a full week, and 2026-09-21 is a Monday, so neither
    # the weekend extension nor any backoff moves the deadline.
    assert_fields(
        resulted,
        chain_status=CHAIN_RESULTED,
        pathology_result=RESULT_BENIGN,
        result_at="2026-09-14T09:00:00.000Z",
        notification_status=NOTIFY_PENDING,
        notification_attempt_count=0,
        escalation_due_at="2026-09-21T09:00:00.000Z",
    )

    # The graded result opened a surveillance obligation of its own, and it is
    # that row — not a second result — which carries the follow-up forward.
    recalls, recall_meta = validate_paginated(
        api.list_surveillance_recalls(
            roster.admin_headers, source_specimen_id=specimen["id"]
        )
    )
    assert recall_meta["total_count"] == 1, (
        "filing a graded result opens exactly one surveillance recall, got "
        f"total_count {recall_meta['total_count']}"
    )
    assert_fields(
        recalls[0],
        patient_id=patient["id"],
        protocol=PROTOCOL_BLADDER_CANCER,
        risk_tier=TIER_LOW,
        anchor_date="2026-09-14",
        interval_months=12,
        due_on="2027-09-14",
        due_basis=BASIS_PROTOCOL_ANCHORED,
        status=RECALL_SCHEDULED_DUE,
    )
    assert_null_fields(recalls[0], "predecessor_recall_id")

    # RESULTED is terminal on the chain dimension: a corrected grade cannot be
    # filed over the top of the first one.
    response = api.result_specimen(
        specimen["id"], f.result_payload(RESULT_MALIGNANT), roster.pathologist_headers
    )
    validate_error(response, ERR_INVALID_SPECIMEN_TRANSITION)

    after = fx.read_specimen(api, roster, specimen["id"])
    assert_fields(
        after,
        chain_status=CHAIN_RESULTED,
        pathology_result=RESULT_BENIGN,
        escalation_due_at="2026-09-21T09:00:00.000Z",
    )


# ─── Instance seven: the two scope guards and the closed stage log ────────────

SCOPE_GUARD_CLOCK = "2026-09-14T09:00:00Z"
SCOPE_GUARD_SECOND_CLOCK = "2026-09-14T11:00:00Z"


def _build_scope_guard_stage(api):
    """
    Two commissioned cystoscopes taken to two different unusable states, and a
    third case still waiting for an instrument.

    SN-A is merely held by a case, so it is `IN_USE` with no leak-test debt.
    SN-B went through a patient cycle and then failed its precleaning stage, so
    the quarantine cascade left it `QUARANTINED` *and* owing a leak test — the one
    scope on which both assignment guards are unmet at once. Both scopes are
    commissioned, because a freshly registered scope has a null high-level
    disinfection stamp and could not be brought into a room at all.
    """
    practice = fx.build_simple_practice(
        api,
        TYPE_CYSTOSCOPY,
        ROOM_TYPE_CYSTO_SUITE,
        type_kwargs={
            "base_minutes": 20,
            "cleanup_class": CLEANUP_HIGH,
            "requires_scope": True,
            "required_prep_codes": [],
        },
        room_kwargs={"name": "Cysto A", "turnover_minutes": 10},
        patient_kwargs={
            "mrn": "MRN-5061",
            "full_name": "Dora Vine",
            "date_of_birth": "1955-05-15",
            "egfr": 80,
        },
    )
    roster = practice["roster"]
    fx.set_clock(api, SCOPE_GUARD_CLOCK, roster.admin_headers)
    scope_a = fx.build_ready_scope(
        api, roster, serial_number="SN-A", scope_model="FlexCysto 200", channel_count=2
    )
    scope_b = fx.build_ready_scope(
        api, roster, serial_number="SN-B", scope_model="FlexCysto 200", channel_count=2
    )
    cases = [
        fx.schedule_new_case(
            api,
            roster,
            practice["patient"],
            practice["procedure_type"],
            practice["room"],
            start_at,
        )
        for start_at in (
            "2026-09-14T09:00:00Z",
            "2026-09-14T11:00:00Z",
            "2026-09-14T13:00:00Z",
        )
    ]
    fx.assign_scope(api, roster, cases[0]["id"], scope_a)
    fx.assign_scope(api, roster, cases[1]["id"], scope_b)

    # The middle case runs its patient through, which soils SN-B and starts its
    # reprocessing clock.
    fx.clear_case(api, roster, cases[1]["id"])
    fx.set_clock(api, SCOPE_GUARD_SECOND_CLOCK, roster.admin_headers)
    fx.check_in_case(api, roster, cases[1]["id"])
    fx.complete_case(api, roster, cases[1]["id"])

    opened_log = validate_success(
        api.create_reprocessing_log(
            f.reprocessing_log_payload(
                scope_asset_id=scope_b["id"],
                performed_by_provider_id=roster.tech["id"],
                stage=STAGE_PRECLEAN,
                case_id=cases[1]["id"],
            ),
            roster.tech_headers,
        ),
        201,
    )
    failed_log = validate_success(
        api.complete_reprocessing_log(
            opened_log["id"],
            f.reprocessing_complete_payload(roster.tech_alt["id"], outcome=OUTCOME_FAIL),
            roster.tech_alt_headers,
        )
    )
    assert_fields(failed_log, log_status=LOG_CLOSED, outcome=OUTCOME_FAIL)

    held_scope = fx.read_scope(api, roster, scope_a["id"])
    assert_fields(held_scope, status=SCOPE_IN_USE, leak_test_required=False)
    quarantined_scope = fx.read_scope(api, roster, scope_b["id"])
    assert_fields(
        quarantined_scope, status=SCOPE_QUARANTINED, leak_test_required=True
    )
    assert_null_fields(quarantined_scope, "reprocess_due_at")

    return roster, cases[2], held_scope, quarantined_scope, failed_log


def test_assigning_a_scope_another_case_is_holding_is_rejected(api):
    """PRD §3.5: "Availability is checked second: a scope whose `status` is
    anything other than `AVAILABLE` — `IN_USE`, `SOILED`, `REPROCESSING` or
    `QUARANTINED` — is refused with `ERR_SCOPE_NOT_AVAILABLE`."

    Design: Corner/errors/err_scope_assignment_state_guards_rejected
    """
    roster, waiting_case, held_scope, _, _ = _build_scope_guard_stage(api)

    # The version carried is the scope's current one and the scope owes no leak
    # test, so availability is the only rule that can fail.
    response = api.assign_scope(
        waiting_case["id"],
        f.scope_assignment_payload(held_scope["id"], held_scope["version"]),
        roster.nurse_headers,
    )
    validate_error(response, ERR_SCOPE_NOT_AVAILABLE)

    case_after = fx.read_case(api, roster, waiting_case["id"])
    assert_null_fields(case_after, "scope_asset_id")
    scope_after = fx.read_scope(api, roster, held_scope["id"])
    assert_version_unchanged(held_scope, scope_after)


def test_assigning_a_quarantined_scope_reports_the_leak_test_debt(api):
    """PRD §3.5: "The leak-test debt is checked first: a scope whose
    `leak_test_required` is true is refused with `ERR_SCOPE_LEAK_TEST_DUE`."
    PRD §3.5: "A soiled scope that also owes a leak test therefore reports the
    leak-test debt, not the availability failure."

    Design: Corner/errors/err_scope_assignment_state_guards_rejected
    """
    roster, waiting_case, _, quarantined_scope, _ = _build_scope_guard_stage(api)

    # This scope is unusable twice over: its status alone would justify the 409
    # of ERR_SCOPE_NOT_AVAILABLE, but the debt is checked first and answers 422.
    response = api.assign_scope(
        waiting_case["id"],
        f.scope_assignment_payload(
            quarantined_scope["id"], quarantined_scope["version"]
        ),
        roster.nurse_headers,
    )
    validate_error(response, ERR_SCOPE_LEAK_TEST_DUE)

    case_after = fx.read_case(api, roster, waiting_case["id"])
    assert_null_fields(case_after, "scope_asset_id")
    scope_after = fx.read_scope(api, roster, quarantined_scope["id"])
    assert_fields(scope_after, status=SCOPE_QUARANTINED, leak_test_required=True)
    assert_version_unchanged(quarantined_scope, scope_after)


def test_completing_an_already_closed_stage_log_is_rejected(api):
    """PRD §3.5: "The log's `log_status` must still be `OPEN`; completing an
    already-closed log is refused with `ERR_INVALID_REPROCESSING_TRANSITION`."
    PRD §3.5: "A successful close sets `log_status` to `CLOSED`, records
    `completed_at` at the logical clock instant, and stores the `outcome`."

    Design: Corner/errors/err_scope_assignment_state_guards_rejected
    """
    roster, _, _, quarantined_scope, failed_log = _build_scope_guard_stage(api)

    # A second close that would overwrite the failing outcome with a pass: the
    # attester is still a different technician, so only the log's own state
    # stands in the way.
    response = api.complete_reprocessing_log(
        failed_log["id"],
        f.reprocessing_complete_payload(roster.tech_alt["id"], outcome=OUTCOME_PASS),
        roster.tech_alt_headers,
    )
    validate_error(response, ERR_INVALID_REPROCESSING_TRANSITION)

    log_after = validate_success(
        api.get_reprocessing_log(failed_log["id"], roster.tech_headers)
    )
    assert_fields(log_after, log_status=LOG_CLOSED, outcome=OUTCOME_FAIL)
    assert log_after["completed_at"] == failed_log["completed_at"], (
        "the rejected close must not restamp completed_at: was "
        f"{failed_log['completed_at']!r}, now {log_after['completed_at']!r}"
    )
    # The quarantine cascade is not re-run either.
    scope_after = fx.read_scope(api, roster, quarantined_scope["id"])
    assert_version_unchanged(quarantined_scope, scope_after)


# ─── Instance eight: the two consignment device guards ───────────────────────

CONSIGNMENT_CLOCK = "2026-09-14T09:00:00Z"
CONSIGNMENT_SECOND_CLOCK = "2026-09-14T11:00:00Z"
BIOPSY_KIT_SKU = "BX-KIT-1"


def _build_consignment_stage(api):
    """
    A biopsy that may not proceed without a consigned device, a ten-unit lot of
    exactly the catalogue number that type names, and two cleared cases on the
    calendar — one holding a single unit, one holding nothing.

    Both cases are cleared and neither needs a scope or prophylaxis, so the only
    check-in gate that can be unmet is the device one.
    """
    practice = fx.build_simple_practice(
        api,
        TYPE_PROSTATE_BIOPSY,
        ROOM_TYPE_CYSTO_SUITE,
        type_kwargs={
            "base_minutes": 30,
            "cleanup_class": CLEANUP_LOW,
            "consignment_required": True,
            "single_use_device_sku": BIOPSY_KIT_SKU,
            "requires_scope": False,
            "requires_specimen": False,
            "requires_antibiotic": False,
            "required_prep_codes": [],
        },
        room_kwargs={"name": "Cysto A", "turnover_minutes": 10},
        patient_kwargs={
            "mrn": "MRN-5062",
            "full_name": "Ivo Salk",
            "date_of_birth": "1952-12-01",
            "egfr": 74,
        },
    )
    roster = practice["roster"]
    lot = fx.create_lot(
        api,
        supplier_name="Medline",
        sku=BIOPSY_KIT_SKU,
        device_class=DEVICE_CLASS_BIOPSY_NEEDLE,
        quantity_received=10,
        unit_price_cents=4500,
        lot_expires_on="2027-06-30",
    )
    fx.set_clock(api, CONSIGNMENT_CLOCK, roster.admin_headers)
    cases = [
        fx.schedule_new_case(
            api,
            roster,
            practice["patient"],
            practice["procedure_type"],
            practice["room"],
            start_at,
        )
        for start_at in ("2026-09-14T09:00:00Z", "2026-09-14T11:00:00Z")
    ]
    fx.clear_case(api, roster, cases[0]["id"])
    fx.clear_case(api, roster, cases[1]["id"])

    holding_case = fx.reserve_device(api, roster, cases[0]["id"], lot, quantity=1)
    assert_fields(holding_case, device_state=DEVICE_STATE_RESERVED, device_quantity=1)
    held_lot = fx.read_lot(api, roster, lot["id"])
    assert_lot_counters(held_lot, available=9, reserved=1, consumed=0, returned=0, wasted=0)

    return roster, holding_case, cases[1], held_lot


def test_second_device_reservation_on_one_case_is_rejected(api):
    """PRD §3.6: "The case's `device_state` must be `NONE` or `RELEASED`, since a
    case already holding `RESERVED`, `CONSUMED` or `WASTED` units may not reserve
    again, or `ERR_DEVICE_ALREADY_RESERVED`."

    Design: Corner/errors/err_device_reservation_guards_rejected
    """
    roster, holding_case, _, held_lot = _build_consignment_stage(api)

    # The lot is in date, the catalogue number matches and eight further units
    # are free, so no other reservation guard can fire: the case's own
    # device_state is the whole reason for the refusal.
    response = api.reserve_device(
        holding_case["id"],
        f.device_reservation_payload(held_lot["id"], 1, held_lot["version"]),
        roster.nurse_headers,
    )
    validate_error(response, ERR_DEVICE_ALREADY_RESERVED)

    case_after = fx.read_case(api, roster, holding_case["id"])
    assert_fields(
        case_after,
        device_state=DEVICE_STATE_RESERVED,
        device_quantity=1,
        device_lot_id=held_lot["id"],
    )
    lot_after = fx.read_lot(api, roster, held_lot["id"])
    assert_lot_counters(lot_after, available=9, reserved=1, consumed=0, returned=0, wasted=0)
    assert_version_unchanged(held_lot, lot_after)


def test_check_in_of_a_consignment_case_without_a_hold_is_rejected(api):
    """PRD §2.8: "When the case's procedure type has `consignment_required` true,
    the case's `device_state` is `RESERVED`. Otherwise `ERR_DEVICE_NOT_RESERVED`,
    HTTP 422."
    PRD §3.7: "`DEVICE_NOT_RESERVED` — the procedure type's
    `consignment_required` is true and the case's `device_state` is not
    `RESERVED`."

    Design: Corner/errors/err_device_reservation_guards_rejected
    """
    roster, _, waiting_case, _ = _build_consignment_stage(api)

    # The clock is moved onto this case's start instant so the early-arrival
    # gate is satisfied and the device gate is the only one left unmet.
    fx.set_clock(api, CONSIGNMENT_SECOND_CLOCK, roster.admin_headers)
    readiness = validate_success(
        api.get_case_readiness(waiting_case["id"], roster.nurse_headers)
    )
    assert_readiness(readiness, [GATE_DEVICE_NOT_RESERVED], check_in_allowed=False)

    response = api.check_in_case(waiting_case["id"], {}, roster.nurse_headers)
    validate_error(response, ERR_DEVICE_NOT_RESERVED)

    case_after = fx.read_case(api, roster, waiting_case["id"])
    assert_fields(
        case_after,
        schedule_status=CASE_SCHEDULED,
        device_state=DEVICE_STATE_NONE,
        device_quantity=0,
    )
    assert_null_fields(case_after, "checked_in_at")


def test_the_same_check_in_succeeds_once_the_case_holds_units(api):
    """PRD §3.6: "A successful hold writes `device_lot_id` and `device_quantity`
    onto the case and sets its `device_state` to `RESERVED`; the lot's
    `quantity_available` falls by the reserved quantity and its
    `quantity_reserved` rises by the same amount; the lot is re-billed
    provisionally, its `billing_status` re-derived and its `version` incremented
    by 1; and the case's readiness gates are recomputed."
    PRD §3.7: "On success the case's `checked_in_at` records the logical clock
    instant and `blocking_reason_codes` collapses to the empty array."

    Design: Corner/errors/err_device_reservation_guards_rejected
    """
    roster, _, waiting_case, held_lot = _build_consignment_stage(api)

    # Two units for the second case, on top of the one unit the first case
    # already holds: the ledger moves three units out of the available bucket.
    reserved_case = fx.reserve_device(api, roster, waiting_case["id"], held_lot, quantity=2)
    assert_fields(
        reserved_case,
        device_state=DEVICE_STATE_RESERVED,
        device_quantity=2,
        device_lot_id=held_lot["id"],
    )
    lot_after = fx.read_lot(api, roster, held_lot["id"])
    assert_lot_counters(lot_after, available=7, reserved=3, consumed=0, returned=0, wasted=0)

    fx.set_clock(api, CONSIGNMENT_SECOND_CLOCK, roster.admin_headers)
    checked_in = validate_success(
        api.check_in_case(waiting_case["id"], {}, roster.nurse_headers)
    )
    # The identical request that was refused a moment ago now passes, so the
    # earlier refusal is attributable to device_state alone.
    assert_fields(
        checked_in,
        schedule_status=CASE_IN_ROOM,
        checked_in_at="2026-09-14T11:00:00.000Z",
        blocking_reason_codes=[],
    )


# ─── Instance nine: the referral visit ledger and its deadline ───────────────

REFERRAL_CLOCK = "2026-09-14T09:00:00Z"
REFERRAL_LATE_CLOCK = "2026-10-15T09:00:00Z"


def _build_referral_stage(api):
    """
    One completed cystoscopy and two referrals opened off it: a biofeedback
    course asking for two visits and a pelvic-floor course asking for one.

    Both start at `REQUESTED` with an empty ledger, which is the state the
    transition guard and the allocation guard are exercised from. The source case
    completed on 2026-09-14, so the thirty-day therapy window closes on
    2026-10-14.
    """
    practice = fx.build_simple_practice(
        api,
        TYPE_CYSTOSCOPY,
        ROOM_TYPE_CYSTO_SUITE,
        type_kwargs={
            "base_minutes": 20,
            "cleanup_class": CLEANUP_HIGH,
            "requires_scope": False,
            "required_prep_codes": [],
        },
        room_kwargs={"name": "Cysto A", "turnover_minutes": 10},
        patient_kwargs={
            "mrn": "MRN-5063",
            "full_name": "Lena Ost",
            "date_of_birth": "1970-07-07",
            "egfr": 88,
        },
    )
    roster = practice["roster"]
    fx.set_clock(api, REFERRAL_CLOCK, roster.admin_headers)
    case = fx.schedule_new_case(
        api,
        roster,
        practice["patient"],
        practice["procedure_type"],
        practice["room"],
        "2026-09-14T09:00:00Z",
    )
    fx.clear_case(api, roster, case["id"])
    fx.check_in_case(api, roster, case["id"])
    completed_case = fx.complete_case(api, roster, case["id"])
    assert_fields(
        completed_case,
        schedule_status=CASE_COMPLETED,
        completed_at="2026-09-14T09:00:00.000Z",
    )

    referral_a = fx.open_referral(
        api,
        roster,
        practice["patient"],
        case["id"],
        program=PROGRAM_BIOFEEDBACK,
        requested_visits=2,
    )
    referral_b = fx.open_referral(
        api,
        roster,
        practice["patient"],
        case["id"],
        program=PROGRAM_PELVIC_FLOOR_PT,
        requested_visits=1,
    )
    for referral in (referral_a, referral_b):
        assert_fields(referral, status=REFERRAL_REQUESTED)
        assert_visit_counters(referral, authorized=0, used=0, remaining=0, forfeited=0)
        assert_null_fields(
            referral, "waitlist_position", "therapy_start_by", "first_visit_date"
        )
    return roster, referral_a, referral_b


def test_logging_a_visit_on_a_requested_referral_is_rejected(api):
    """PRD §3.9: "Logging a visit on a referral that is `REQUESTED`, `DECLINED`,
    `WAITLISTED` or `WITHDRAWN`, by contrast, is undeclared and answers
    `ERR_INVALID_REFERRAL_TRANSITION`."

    Design: Corner/errors/err_referral_visit_ledger_rejected
    """
    roster, referral_a, _ = _build_referral_stage(api)

    response = api.log_referral_visit(
        referral_a["id"],
        f.referral_visit_payload(VISIT_ACTION_LOG, visit_date="2026-09-15"),
        roster.coordinator_headers,
    )
    validate_error(response, ERR_INVALID_REFERRAL_TRANSITION)

    after = fx.read_referral(api, roster, referral_a["id"])
    assert_fields(after, status=REFERRAL_REQUESTED)
    assert_visit_counters(after, authorized=0, used=0, remaining=0, forfeited=0)
    assert_null_fields(after, "first_visit_date")


def test_voiding_against_an_empty_ledger_reports_the_allocation_not_the_transition(api):
    """PRD §3.9: "Note where that check sits relative to the transition guard:
    `VOID_LAST` is a declared action on every accepted referral, so voiding
    against an empty ledger is *not* an undeclared transition — it passes the
    transition guard and is caught by the allocation check, which is why it
    answers `ERR_VISIT_ALLOCATION_EXHAUSTED` rather than
    `ERR_INVALID_REFERRAL_TRANSITION`."
    PRD §2.8: "With `action` `LOG`, `visits_remaining` is at least 1; with
    `action` `VOID_LAST`, `visits_used` is at least 1."

    Design: Corner/errors/err_referral_visit_ledger_rejected
    """
    roster, referral_a, _ = _build_referral_stage(api)

    accepted = fx.accept_referral(api, roster, referral_a["id"], authorized_visits=2)
    # The smallest of the requested 2, the approved 2 and the biofeedback
    # ceiling of 6.
    assert_fields(
        accepted, status=REFERRAL_ACCEPTED, therapy_start_by="2026-10-14"
    )
    assert_visit_counters(accepted, authorized=2, used=0, remaining=2, forfeited=0)
    assert_null_fields(accepted, "waitlist_position", "first_visit_date")

    response = api.log_referral_visit(
        referral_a["id"],
        f.referral_visit_payload(VISIT_ACTION_VOID_LAST),
        roster.coordinator_headers,
    )
    validate_error(response, ERR_VISIT_ALLOCATION_EXHAUSTED)

    after = fx.read_referral(api, roster, referral_a["id"])
    assert_fields(after, status=REFERRAL_ACCEPTED)
    assert_visit_counters(after, authorized=2, used=0, remaining=2, forfeited=0)


def test_logging_past_the_authorised_course_is_rejected(api):
    """PRD §3.9: "`LOG` moves one unit across the ledger: `visits_used` increases
    by 1, `visits_remaining` decreases by 1, and `first_visit_date` holds the
    earliest logged visit date still standing."
    PRD §3.9: "When that log drives `visits_remaining` to 0 the referral
    auto-advances from `ACCEPTED` to `COMPLETED` in the same operation, with no
    further ledger movement beyond the unit just logged."

    Design: Corner/errors/err_referral_visit_ledger_rejected
    """
    roster, referral_a, _ = _build_referral_stage(api)
    fx.accept_referral(api, roster, referral_a["id"], authorized_visits=2)

    first = validate_success(
        api.log_referral_visit(
            referral_a["id"],
            f.referral_visit_payload(VISIT_ACTION_LOG, visit_date="2026-09-15"),
            roster.coordinator_headers,
        )
    )
    assert_fields(
        first, status=REFERRAL_ACCEPTED, first_visit_date="2026-09-15"
    )
    assert_visit_counters(first, authorized=2, used=1, remaining=1, forfeited=0)

    second = validate_success(
        api.log_referral_visit(
            referral_a["id"],
            f.referral_visit_payload(VISIT_ACTION_LOG, visit_date="2026-09-22"),
            roster.coordinator_headers,
        )
    )
    assert_fields(
        second, status=REFERRAL_COMPLETED, first_visit_date="2026-09-15"
    )
    assert_visit_counters(second, authorized=2, used=2, remaining=0, forfeited=0)

    # A third session on a two-visit authorisation: the course is both finished
    # and out of units, and the contract enumerates the statuses from which a log
    # is undeclared without settling COMPLETED, so either refusal is faithful to
    # the rules as written — but a refusal there must be, and the ledger may not
    # move.
    response = api.log_referral_visit(
        referral_a["id"],
        f.referral_visit_payload(VISIT_ACTION_LOG, visit_date="2026-09-29"),
        roster.coordinator_headers,
    )
    validate_error_is_one_of(
        response, [ERR_INVALID_REFERRAL_TRANSITION, ERR_VISIT_ALLOCATION_EXHAUSTED]
    )

    after = fx.read_referral(api, roster, referral_a["id"])
    assert_fields(
        after, status=REFERRAL_COMPLETED, first_visit_date="2026-09-15"
    )
    assert_visit_counters(after, authorized=2, used=2, remaining=0, forfeited=0)


def test_accepting_a_referral_past_the_thirty_day_window_is_rejected(api):
    """PRD §3.9: "It is also the only branch with a deadline: the logical clock's
    date must be on or before the source case's `completed_at` date plus 30 days,
    and a referral accepted more than 30 days after its source procedure finished
    is refused with `ERR_THERAPY_START_WINDOW_MISSED`."
    PRD §3.9: "The new referral starts at `status` `REQUESTED` with
    `visits_authorized`, `visits_used`, `visits_remaining` and `visits_forfeited`
    all 0, and with `waitlist_position`, `therapy_start_by`, `first_visit_date`
    and `decline_reason` all null."

    Design: Corner/errors/err_referral_visit_ledger_rejected
    """
    roster, referral_a, referral_b = _build_referral_stage(api)

    # The sibling referral off the same case is accepted while the clock still
    # sits on the day of the procedure, which proves the acceptance itself is
    # well formed and the later refusal is the deadline's doing.
    accepted = fx.accept_referral(api, roster, referral_a["id"], authorized_visits=2)
    assert_fields(accepted, status=REFERRAL_ACCEPTED, therapy_start_by="2026-10-14")

    # One day past 2026-09-14 plus thirty days.
    fx.set_clock(api, REFERRAL_LATE_CLOCK, roster.admin_headers)
    response = api.decide_pelvic_health_referral(
        referral_b["id"],
        f.referral_decision_payload(DECISION_ACCEPT, authorized_visits=1),
        roster.coordinator_headers,
    )
    validate_error(response, ERR_THERAPY_START_WINDOW_MISSED)

    after = fx.read_referral(api, roster, referral_b["id"])
    assert_fields(after, status=REFERRAL_REQUESTED)
    assert_visit_counters(after, authorized=0, used=0, remaining=0, forfeited=0)
    assert_null_fields(after, "therapy_start_by", "waitlist_position")
    assert_version_unchanged(referral_b, after)
