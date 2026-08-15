"""First-article inspection lifecycle, ballooning, measurement, SoD (PRD §2.9, §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_characteristic,
    api_client,
    assert_characteristic,
    assert_fai,
    create_fai,
    create_fai_payload,
    record_measurement,
    setup_fai_submitted,
    setup_fai_with_measured_characteristic,
    validate_error,
    validate_success,
)

QI = TEST_USERS["quality_inspector"]  # insp-1
QI2 = TEST_USERS["quality_inspector_2"]  # insp-2
QI3 = TEST_USERS["quality_inspector_3"]  # insp-3
CQR = TEST_USERS["customer_quality_rep"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / fai_reject_reopen_cycle
# ---------------------------------------------------------------------------

def test_fai_reject_reopen_resubmit_cycle(api):
    """PRD §3.4: "Rejection instead moves `SUBMITTED → REJECTED` with a
    recorded `reason`. A `QualityInspector` may reopen a rejected inspection —
    `REJECTED → IN_INSPECTION`, the rework loop — while reopening from any
    other state fails with `ERR_FAI_NOT_REOPENABLE`."

    Design: Difficulty/non_linear_state_machine/fai_reject_reopen_cycle
    """
    fai = setup_fai_submitted()
    rejected = validate_success(
        api_client.reject_fai(fai["id"], {"reason": "customer requires re-balloon of note 4"}, CQR),
        expected_status=200,
    )
    assert rejected["status"] == "REJECTED"
    reopened = validate_success(api_client.reopen_fai(fai["id"], QI), expected_status=200)
    assert reopened["status"] == "IN_INSPECTION", (
        f"reopen cycles REJECTED back to IN_INSPECTION, got {reopened['status']}"
    )
    resubmitted = validate_success(api_client.submit_fai(fai["id"], QI2), expected_status=200)
    assert resubmitted["status"] == "SUBMITTED"


def test_fai_approve_after_rework_cycle_pins_revision(api):
    """PRD §3.4: "A `CustomerQualityRep` approves a `SUBMITTED` inspection to
    `APPROVED` — from any other state, `ERR_FAI_NOT_SUBMITTED` — which pins
    `approved_revision` equal to the inspection's `part_revision`, freezing
    the approved revision at the moment of approval, and supersedes every
    other `APPROVED` inspection of the same `part_number` and `part_revision`,
    moving each to the terminal `SUPERSEDED` state."

    Design: Difficulty/non_linear_state_machine/fai_reject_reopen_cycle
    """
    fai = setup_fai_submitted(part_revision="A")
    validate_success(
        api_client.reject_fai(fai["id"], {"reason": "rework required"}, CQR)
    )
    validate_success(api_client.reopen_fai(fai["id"], QI))
    validate_success(api_client.submit_fai(fai["id"], QI2))
    approved = validate_success(api_client.approve_fai(fai["id"], CQR), expected_status=200)
    assert_fai(approved)
    assert approved["status"] == "APPROVED"
    assert approved["approved_revision"] == "A", (
        f"approval pins approved_revision to part_revision 'A', got "
        f"{approved['approved_revision']}"
    )


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / fai_submit_state_beats_incomplete
# ---------------------------------------------------------------------------

def test_fai_submit_draft_state_error_masks_completeness(api):
    """PRD §3.4: "The checks run in §2.11 order: an inspection not in
    `IN_INSPECTION` fails with `ERR_FAI_NOT_SUBMITTABLE`; then segregation of
    duties — the submitter's `X-User-ID` must differ from the
    `measured_by_user_id` of every characteristic, failing with
    `ERR_SOD_VIOLATION`; then the content gates — an inspection with zero
    characteristics or any still `UNMEASURED` fails with
    `ERR_FAI_INCOMPLETE_CHARACTERISTICS`, and one carrying any `FAIL` result
    fails with `ERR_FAI_CHARACTERISTIC_FAILURE`."

    Design: Difficulty/priority_pair_validation_conflict/fai_submit_state_beats_incomplete
    """
    fai = create_fai()  # DRAFT, zero characteristics
    resp = api_client.submit_fai(fai["id"], QI2)
    validate_error(resp, ApiErrorId.ERR_FAI_NOT_SUBMITTABLE.value)


def test_fai_submit_draft_leaves_state_unchanged(api):
    """PRD §3.4: "The checks run in §2.11 order: an inspection not in
    `IN_INSPECTION` fails with `ERR_FAI_NOT_SUBMITTABLE`; then segregation of
    duties — the submitter's `X-User-ID` must differ from the
    `measured_by_user_id` of every characteristic, failing with
    `ERR_SOD_VIOLATION`; then the content gates — an inspection with zero
    characteristics or any still `UNMEASURED` fails with
    `ERR_FAI_INCOMPLETE_CHARACTERISTICS`, and one carrying any `FAIL` result
    fails with `ERR_FAI_CHARACTERISTIC_FAILURE`."

    Design: Difficulty/priority_pair_validation_conflict/fai_submit_state_beats_incomplete
    """
    fai = create_fai()  # DRAFT, zero characteristics
    resp = api_client.submit_fai(fai["id"], QI2)
    err = validate_error(resp, ApiErrorId.ERR_FAI_NOT_SUBMITTABLE.value)
    assert err["error_id"] != "ERR_FAI_INCOMPLETE_CHARACTERISTICS", (
        "the state gate must mask the completeness constraint on a DRAFT FAI"
    )
    after = validate_success(api_client.get_fai(fai["id"], QI))
    assert after["status"] == "DRAFT", "a rejected submit leaves the FAI in DRAFT"


# ---------------------------------------------------------------------------
# Corner: entities / fai_create_invalid_enum
# ---------------------------------------------------------------------------

def test_fai_create_invalid_enum(api):
    """PRD §3.4: "A `QualityInspector` opens an FAI with a `part_number`, a
    `part_revision`, and a `fai_type` — `FULL` for a new part or revision,
    `PARTIAL` for a delta or change FAI — and the inspection starts in
    `DRAFT`."
    PRD §2.11: "Malformed request payloads — a missing or invalid required
    field, an invalid enum value, an unknown field, or a non-positive quantity
    — fail with `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/fai_create_invalid_enum
    """
    payload = create_fai_payload(fai_type="DELTA")
    resp = api_client.create_fai(payload, QI)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner: entities / characteristic_negative_tolerance_rejected
# ---------------------------------------------------------------------------

def test_characteristic_negative_tolerance_rejected(api):
    """PRD §3.4: "The inspector adds each characteristic with a
    `balloon_number` unique within the inspection (a duplicate fails with
    `ERR_BALLOON_NUMBER_EXISTS`, 409), a `nominal` dimension, a non-negative
    `tolerance_plus` and `tolerance_minus`, and an optional
    `is_key_characteristic` flag (defaulting to false) designating a key
    characteristic that will require SPC in production."
    PRD §2.11: "Malformed request payloads — a missing or invalid required
    field, an invalid enum value, an unknown field, or a non-positive quantity
    — fail with `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/characteristic_negative_tolerance_rejected
    """
    fai = create_fai()
    resp = api_client.add_characteristic(
        fai["id"],
        {
            "balloon_number": 1,
            "nominal": 10.0,
            "tolerance_plus": 0.1,
            "tolerance_minus": -0.1,
        },
        QI,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner: calculations / fai_completeness_aggregation
# ---------------------------------------------------------------------------

def test_fai_completeness_aggregation(api):
    """PRD §3.4: "After every characteristic added and every measurement
    recorded, the inspection recomputes its completeness bookkeeping:
    `characteristic_count` counts its ballooned characteristics,
    `measured_count` counts those whose `result` is `PASS` or `FAIL`, and
    `characteristics_complete` is true exactly when at least one
    characteristic exists and every one of them has been measured."

    Design: Corner/calculations/fai_completeness_aggregation
    """
    fai = create_fai()
    c1 = add_characteristic(fai["id"], balloon_number=1, nominal=10.0,
                            tolerance_plus=0.1, tolerance_minus=0.1)
    c2 = add_characteristic(fai["id"], balloon_number=2, nominal=20.0,
                            tolerance_plus=0.2, tolerance_minus=0.2)

    mid = validate_success(api_client.get_fai(fai["id"], QI))
    assert mid["characteristic_count"] == 2
    assert mid["measured_count"] == 0
    assert mid["characteristics_complete"] is False

    record_measurement(c1["id"], 10.0)
    mid = validate_success(api_client.get_fai(fai["id"], QI))
    assert mid["measured_count"] == 1
    assert mid["characteristics_complete"] is False

    record_measurement(c2["id"], 20.1)
    done = validate_success(api_client.get_fai(fai["id"], QI))
    assert done["measured_count"] == 2
    assert done["characteristics_complete"] is True, (
        "complete exactly when at least one characteristic exists and all are measured"
    )


# ---------------------------------------------------------------------------
# Corner: validations / balloon_number_uniqueness_rejected
# ---------------------------------------------------------------------------

def test_balloon_number_uniqueness_rejected(api):
    """PRD §3.4: "The inspector adds each characteristic with a
    `balloon_number` unique within the inspection (a duplicate fails with
    `ERR_BALLOON_NUMBER_EXISTS`, 409), a `nominal` dimension, a non-negative
    `tolerance_plus` and `tolerance_minus`, and an optional
    `is_key_characteristic` flag (defaulting to false) designating a key
    characteristic that will require SPC in production."

    Design: Corner/validations/balloon_number_uniqueness_rejected
    """
    fai = create_fai()
    add_characteristic(fai["id"], balloon_number=1)
    resp = api_client.add_characteristic(
        fai["id"],
        {
            "balloon_number": 1,
            "nominal": 20.0,
            "tolerance_plus": 0.2,
            "tolerance_minus": 0.2,
        },
        QI,
    )
    validate_error(resp, ApiErrorId.ERR_BALLOON_NUMBER_EXISTS.value)


# ---------------------------------------------------------------------------
# Corner: validations / fai_submit_incomplete_constraint
# ---------------------------------------------------------------------------

def test_fai_submit_incomplete_constraint(api):
    """PRD §3.4: "The checks run in §2.11 order: an inspection not in
    `IN_INSPECTION` fails with `ERR_FAI_NOT_SUBMITTABLE`; then segregation of
    duties — the submitter's `X-User-ID` must differ from the
    `measured_by_user_id` of every characteristic, failing with
    `ERR_SOD_VIOLATION`; then the content gates — an inspection with zero
    characteristics or any still `UNMEASURED` fails with
    `ERR_FAI_INCOMPLETE_CHARACTERISTICS`, and one carrying any `FAIL` result
    fails with `ERR_FAI_CHARACTERISTIC_FAILURE`."

    Design: Corner/validations/fai_submit_incomplete_constraint
    """
    fai = create_fai()
    add_characteristic(fai["id"], balloon_number=1)  # left UNMEASURED
    resp = api_client.submit_fai(fai["id"], QI2)
    validate_error(resp, ApiErrorId.ERR_FAI_INCOMPLETE_CHARACTERISTICS.value)


# ---------------------------------------------------------------------------
# Corner: validations / fai_submit_failing_characteristic
# ---------------------------------------------------------------------------

def test_fai_submit_failing_characteristic(api):
    """PRD §3.4: "The checks run in §2.11 order: an inspection not in
    `IN_INSPECTION` fails with `ERR_FAI_NOT_SUBMITTABLE`; then segregation of
    duties — the submitter's `X-User-ID` must differ from the
    `measured_by_user_id` of every characteristic, failing with
    `ERR_SOD_VIOLATION`; then the content gates — an inspection with zero
    characteristics or any still `UNMEASURED` fails with
    `ERR_FAI_INCOMPLETE_CHARACTERISTICS`, and one carrying any `FAIL` result
    fails with `ERR_FAI_CHARACTERISTIC_FAILURE`."

    Design: Corner/validations/fai_submit_failing_characteristic
    """
    fai = create_fai()
    char = add_characteristic(fai["id"], balloon_number=1)
    failing = record_measurement(char["id"], 10.2)  # above usl 10.10
    assert failing["result"] == "FAIL"
    resp = api_client.submit_fai(fai["id"], QI2)
    validate_error(resp, ApiErrorId.ERR_FAI_CHARACTERISTIC_FAILURE.value)


# ---------------------------------------------------------------------------
# Corner: validations / fai_submit_self_inspection_forbidden
# ---------------------------------------------------------------------------

def test_fai_submit_self_inspection_forbidden(api):
    """PRD §2.9: "First, the inspector who submits a first-article inspection
    must not be the inspector who recorded any of its characteristic
    measurements: the submitter's `X-User-ID` must differ from the
    `measured_by_user_id` of every characteristic on the inspection."
    PRD §2.9: "Three operations enforce segregation of duties by comparing the
    caller's `X-User-ID` to an identifier anchored on the resource, rejecting
    a match with `ERR_SOD_VIOLATION` (403)."

    Design: Corner/validations/fai_submit_self_inspection_forbidden
    """
    fai, _char = setup_fai_with_measured_characteristic(measured_value=10.0)
    # insp-1 recorded the only measurement; insp-1 may not submit.
    resp = api_client.submit_fai(fai["id"], QI)
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / fai_approve_from_draft_returns_invalid_state
# ---------------------------------------------------------------------------

def test_fai_approve_from_draft_returns_invalid_state(api):
    """PRD §3.4: "A `CustomerQualityRep` approves a `SUBMITTED` inspection to
    `APPROVED` — from any other state, `ERR_FAI_NOT_SUBMITTED` — which pins
    `approved_revision` equal to the inspection's `part_revision`, freezing
    the approved revision at the moment of approval, and supersedes every
    other `APPROVED` inspection of the same `part_number` and `part_revision`,
    moving each to the terminal `SUPERSEDED` state."

    Design: Corner/state_machines/fai_approve_from_draft_returns_invalid_state
    """
    fai = create_fai()  # DRAFT
    resp = api_client.approve_fai(fai["id"], CQR)
    validate_error(resp, ApiErrorId.ERR_FAI_NOT_SUBMITTED.value)
    after = validate_success(api_client.get_fai(fai["id"], QI))
    assert after["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner: state_machines / fai_supersede_terminal_lockdown
# ---------------------------------------------------------------------------

def test_fai_supersede_terminal_lockdown(api):
    """PRD §3.4: "A `CustomerQualityRep` approves a `SUBMITTED` inspection to
    `APPROVED` — from any other state, `ERR_FAI_NOT_SUBMITTED` — which pins
    `approved_revision` equal to the inspection's `part_revision`, freezing
    the approved revision at the moment of approval, and supersedes every
    other `APPROVED` inspection of the same `part_number` and `part_revision`,
    moving each to the terminal `SUPERSEDED` state."

    Design: Corner/state_machines/fai_supersede_terminal_lockdown
    """
    fai1 = setup_fai_submitted(part_number="P112", part_revision="A")
    fai1 = validate_success(api_client.approve_fai(fai1["id"], CQR))
    assert fai1["status"] == "APPROVED"

    fai2 = setup_fai_submitted(part_number="P112", part_revision="A")
    fai2 = validate_success(api_client.approve_fai(fai2["id"], CQR))
    assert fai2["status"] == "APPROVED"

    fai1_after = validate_success(api_client.get_fai(fai1["id"], QI))
    assert fai1_after["status"] == "SUPERSEDED", (
        f"approving a second FAI for the same part+revision supersedes the "
        f"first, got {fai1_after['status']}"
    )
    resp = api_client.reject_fai(fai1["id"], {"reason": "late rejection"}, CQR)
    validate_error(resp, ApiErrorId.ERR_FAI_NOT_SUBMITTED.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / characteristic_remeasure_fail_to_pass
# ---------------------------------------------------------------------------

def test_characteristic_remeasure_fail_to_pass(api):
    """PRD §3.4: "Recording a `measured_value` is permitted only while the
    characteristic's `result` is `UNMEASURED` or `FAIL` — re-measuring a `PASS`
    characteristic fails with `ERR_CHARACTERISTIC_NOT_MEASURABLE` — and only
    while the parent inspection remains `DRAFT` or `IN_INSPECTION`
    (`ERR_CHARACTERISTIC_LOCKED` otherwise)."
    PRD §3.4: "The recorder's identity is anchored as `measured_by_user_id`,
    and a re-measurement after rework overwrites both the stored value and the
    anchor."

    Design: Corner/state_machines/characteristic_remeasure_fail_to_pass
    """
    fai = create_fai()
    char = add_characteristic(fai["id"], balloon_number=1)
    first = record_measurement(char["id"], 10.2)  # usl is 10.10
    assert first["result"] == "FAIL", f"10.2 > usl 10.10 must FAIL, got {first['result']}"
    second = record_measurement(char["id"], 10.05)
    assert_characteristic(second)
    assert second["result"] == "PASS", (
        f"re-measurement within limits moves FAIL -> PASS, got {second['result']}"
    )
    assert second["measured_value"] == 10.05, (
        f"re-measurement overwrites the stored value, got {second['measured_value']}"
    )


# ---------------------------------------------------------------------------
# Corner: state_machines / characteristic_pass_remeasure_rejected
# ---------------------------------------------------------------------------

def test_characteristic_pass_remeasure_rejected(api):
    """PRD §3.4: "Recording a `measured_value` is permitted only while the
    characteristic's `result` is `UNMEASURED` or `FAIL` — re-measuring a `PASS`
    characteristic fails with `ERR_CHARACTERISTIC_NOT_MEASURABLE` — and only
    while the parent inspection remains `DRAFT` or `IN_INSPECTION`
    (`ERR_CHARACTERISTIC_LOCKED` otherwise)."

    Design: Corner/state_machines/characteristic_pass_remeasure_rejected
    """
    fai = create_fai()
    char = add_characteristic(fai["id"], balloon_number=1)
    passed = record_measurement(char["id"], 10.0)
    assert passed["result"] == "PASS"
    resp = api_client.record_measurement(char["id"], {"measured_value": 10.01}, QI)
    validate_error(resp, ApiErrorId.ERR_CHARACTERISTIC_NOT_MEASURABLE.value)
