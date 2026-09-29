"""Return-to-sport stage cycling, the clearance-document dependency, and duty segregation."""
from test_helpers import (
    advance_clock,
    create_clearance_document,
    fetch_athlete,
    fetch_clearance_document,
    fetch_rts_plan,
    make_medical_provider_headers,
    open_and_finalize_stage_test,
    setup_athlete_on_medical_hold,
    setup_plan_at_stage_testing,
    validate_error,
    validate_success,
)


def test_01_a_first_failed_stage_returns_the_plan_to_the_same_stage(
        api, medical_provider_headers):
    """The plan re-enters STAGE_ACTIVE with the stage held and both counters raised.

    "**First `FAIL` at a stage** (the attempt count after incrementing is still below
    2): `stage_attempts` rises by one, `total_failed_attempts` rises by one,
    `current_stage` is unchanged, `active_stage_test_id` is cleared to null, and the
    plan returns `STAGE_TESTING → STAGE_ACTIVE` so the stage can be re-tested."

    Design: Difficulty/non_linear_state_machine/rts_plan_cycles_back_to_stage_active_by_fail_then_by_pass
    """
    athlete, _staff, _coach_headers, _injury, plan, stage_test = (
        setup_plan_at_stage_testing(
            athlete_overrides={"full_name": "Zoe Ivanova",
                               "date_of_birth": "2010-01-15"},
            target_stage_count=3))
    assert plan["status"] == "STAGE_TESTING"
    assert plan["active_stage_test_id"] == stage_test["id"]

    failed = validate_success(api.record_stage_decision(
        plan["id"], {"decision": "FAIL"}, medical_provider_headers))

    assert failed["status"] == "STAGE_ACTIVE"
    assert failed["current_stage"] == 1, "a first failure never advances the stage"
    assert failed["stage_attempts"] == 1
    assert failed["total_failed_attempts"] == 1
    assert failed["active_stage_test_id"] is None
    assert fetch_athlete(athlete["id"])["training_clearance"] == "RESTRICTED"


def test_02_a_pass_re_enters_the_same_state_with_the_opposite_counter_effect(
        api, medical_provider_headers):
    """The second route into STAGE_ACTIVE advances the stage and resets the attempts.

    "**`PASS` below the final stage** (`current_stage` less than
    `target_stage_count`): `current_stage` rises by one, `stage_attempts` resets to 0,
    `active_stage_test_id` is cleared to null, and the plan returns `STAGE_TESTING →
    STAGE_ACTIVE` to begin the next stage."

    "The operation moves the plan `STAGE_ACTIVE → STAGE_TESTING` and creates a fresh
    test session on the athlete's behalf: `battery_type` of `PERFORMANCE_BATTERY`,
    `status` of `DRAFT`, `athlete_id` taken from the plan, `rts_plan_id` pointing back
    at the plan, and `administered_by_staff_id` set to the acting coach's `X-User-ID` —
    the same identity that is then barred from judging the result."

    Design: Difficulty/non_linear_state_machine/rts_plan_cycles_back_to_stage_active_by_fail_then_by_pass
    """
    athlete, _staff, coach_headers, _injury, plan, _stage_test = (
        setup_plan_at_stage_testing(
            athlete_overrides={"full_name": "Zoe Ivanova",
                               "date_of_birth": "2010-01-15"},
            target_stage_count=3))
    validate_success(api.record_stage_decision(plan["id"], {"decision": "FAIL"},
                                               medical_provider_headers))
    open_and_finalize_stage_test(plan["id"], coach_headers)
    document = create_clearance_document(
        athlete["id"], "STAGE_CLEARANCE", expires_on="2026-12-31",
        rts_plan_id=plan["id"], stage_number=1)
    validate_success(api.sign_clearance_document(
        document["id"], {"provider_license_id": "MD-31-8842"},
        medical_provider_headers))

    passed = validate_success(api.record_stage_decision(
        plan["id"], {"decision": "PASS"}, medical_provider_headers))

    assert passed["status"] == "STAGE_ACTIVE"
    assert passed["current_stage"] == 2
    assert passed["stage_attempts"] == 0, "the retry budget resets for the new stage"
    assert passed["total_failed_attempts"] == 1, \
        "the lifetime failure count survives the successful stage"
    assert passed["active_stage_test_id"] is None

    reopened = validate_success(api.open_stage_test(plan["id"], coach_headers),
                                expected_status=201)

    assert reopened["battery_type"] == "PERFORMANCE_BATTERY"
    assert reopened["status"] == "DRAFT"
    assert reopened["rts_plan_id"] == plan["id"]
    cycled = fetch_rts_plan(plan["id"])
    assert cycled["status"] == "STAGE_TESTING"
    assert cycled["current_stage"] == 2
    assert cycled["stage_attempts"] == 0
    assert cycled["total_failed_attempts"] == 1
    assert cycled["active_stage_test_id"] == reopened["id"]
    assert fetch_athlete(athlete["id"])["training_clearance"] == "RESTRICTED"


def test_03_a_pass_is_refused_while_the_stage_clearance_is_only_pending(
        api, medical_provider_headers):
    """The document exists but has not been signed, so the safety gate holds.

    "A `PASS` additionally requires a clearance document for this plan whose
    `document_type` is `STAGE_CLEARANCE`, whose `stage_number` equals the plan's
    `current_stage`, whose `status` is `SIGNED` and unrevoked, and whose `expires_on` is
    on or after the current logical date. A missing or unsigned or revoked document
    returns `ERR_STAGE_CLEARANCE_MISSING`; a document whose `expires_on` has already
    passed returns `ERR_CLEARANCE_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/rts_stage_pass_blocked_until_clearance_document_reaches_signed
    """
    athlete, _staff, _coach_headers, _injury, plan, stage_test = (
        setup_plan_at_stage_testing(
            athlete_overrides={"full_name": "Iker Ruiz",
                               "date_of_birth": "2010-01-15"},
            target_stage_count=3))
    document = create_clearance_document(
        athlete["id"], "STAGE_CLEARANCE", expires_on="2026-12-31",
        rts_plan_id=plan["id"], stage_number=1)
    assert document["status"] == "PENDING"

    validate_error(
        api.record_stage_decision(plan["id"], {"decision": "PASS"},
                                  medical_provider_headers),
        "ERR_STAGE_CLEARANCE_MISSING", expected_status=422)

    unchanged = fetch_rts_plan(plan["id"])
    assert unchanged["status"] == "STAGE_TESTING"
    assert unchanged["current_stage"] == 1
    assert unchanged["stage_attempts"] == 0
    assert unchanged["total_failed_attempts"] == 0
    assert unchanged["active_stage_test_id"] == stage_test["id"]
    assert fetch_clearance_document(document["id"])["status"] == "PENDING"


def test_04_the_identical_pass_is_accepted_once_the_document_is_signed(
        api, medical_provider_headers):
    """Nothing about the plan or the acting provider changes; only the document does.

    "On success `status` moves `PENDING → SIGNED` and `signed_at` is stamped from the
    logical clock, after which the effect depends on `document_type`:"

    "A signed `STAGE_CLEARANCE` changes no state anywhere. It simply becomes the
    precondition a `PASS` decision at that `stage_number` requires."

    Design: Difficulty/cross_entity_state_dependency/rts_stage_pass_blocked_until_clearance_document_reaches_signed
    """
    athlete, _staff, _coach_headers, _injury, plan, _stage_test = (
        setup_plan_at_stage_testing(
            athlete_overrides={"full_name": "Iker Ruiz",
                               "date_of_birth": "2010-01-15"},
            target_stage_count=3))
    document = create_clearance_document(
        athlete["id"], "STAGE_CLEARANCE", expires_on="2026-12-31",
        rts_plan_id=plan["id"], stage_number=1)
    validate_error(
        api.record_stage_decision(plan["id"], {"decision": "PASS"},
                                  medical_provider_headers),
        "ERR_STAGE_CLEARANCE_MISSING", expected_status=422)

    signed = validate_success(api.sign_clearance_document(
        document["id"], {"provider_license_id": "MD-31-8842"},
        medical_provider_headers))
    assert signed["status"] == "SIGNED"
    assert signed["provider_license_id"] == "MD-31-8842"
    assert signed["signed_at"] is not None

    passed = validate_success(api.record_stage_decision(
        plan["id"], {"decision": "PASS"}, medical_provider_headers))

    assert passed["status"] == "STAGE_ACTIVE"
    assert passed["current_stage"] == 2
    assert passed["stage_attempts"] == 0
    assert passed["total_failed_attempts"] == 0
    assert passed["active_stage_test_id"] is None
    assert fetch_athlete(athlete["id"])["training_clearance"] == "RESTRICTED", \
        "a stage clearance authorises one decision and changes no other state"


def test_05_a_new_clearance_document_opens_unsigned(api, medical_provider_headers):
    """Creation records the intent only; the document carries no signature yet.

    "Every document is created `PENDING`, with `provider_license_id` and `signed_at`
    null. `PENDING` documents do nothing until signed."

    "`MEDICAL_HOLD_RELEASE` lifts a medical hold on the athlete directly. Its
    `rts_plan_id` **must** be null and its `stage_number` must be null."

    Design: Corner/state_machines/clearance_document_initial_state_is_pending
    """
    athlete, _staff, _coach_headers = setup_athlete_on_medical_hold(
        athlete_overrides={"full_name": "Hold Athlete",
                           "date_of_birth": "2009-02-02"})
    assert athlete["training_clearance"] == "MEDICAL_HOLD"

    created = validate_success(api.create_clearance_document(
        {"athlete_id": athlete["id"], "rts_plan_id": None,
         "document_type": "MEDICAL_HOLD_RELEASE", "stage_number": None,
         "expires_on": "2026-12-31"}, medical_provider_headers),
        expected_status=201)

    assert created["status"] == "PENDING"
    assert created["signed_at"] is None
    assert created["provider_license_id"] is None
    assert created["document_type"] == "MEDICAL_HOLD_RELEASE"
    assert created["stage_number"] is None
    assert created["rts_plan_id"] is None
    assert created["version"] == 1
    assert fetch_athlete(athlete["id"])["training_clearance"] == "MEDICAL_HOLD", \
        "an unsigned document lifts nothing"


def test_06_an_expired_document_can_no_longer_be_signed(api, medical_provider_headers):
    """The clock passed the validity end date, and the signing validation refuses it.

    "The document must be `PENDING` and its `expires_on` must be on or after the
    current logical date; an already-expired document is refused with
    `ERR_CLEARANCE_EXPIRED`."

    "First, every `ClearanceDocument` whose `status` is `SIGNED` and whose `expires_on`
    falls earlier than the new logical date moves to `EXPIRED`."

    Design: Corner/errors/signing_a_clearance_document_past_its_expiry_returns_clearance_expired
    """
    athlete, _staff, _coach_headers = setup_athlete_on_medical_hold(
        athlete_overrides={"full_name": "Stale Document Athlete",
                           "date_of_birth": "2009-02-02"})
    document = create_clearance_document(
        athlete["id"], "MEDICAL_HOLD_RELEASE", expires_on="2026-08-10",
        rts_plan_id=None, stage_number=None)

    swept = advance_clock("2026-08-20T09:00:00Z")
    assert swept["clearance_documents_expired_count"] == 0, \
        "the sweep only expires signed documents"

    validate_error(
        api.sign_clearance_document(document["id"],
                                    {"provider_license_id": "MD-77-2291"},
                                    medical_provider_headers),
        "ERR_CLEARANCE_EXPIRED", expected_status=422)

    reread = fetch_clearance_document(document["id"])
    assert reread["status"] == "PENDING", \
        "the refusal comes from the signing validation, not from a swept status"
    assert reread["signed_at"] is None
    assert reread["provider_license_id"] is None
    assert fetch_athlete(athlete["id"])["training_clearance"] == "MEDICAL_HOLD"


def test_07_the_coach_who_administered_the_stage_test_cannot_judge_it(api):
    """Holding the provider role is not enough when the acting identity ran the test.

    "Three preconditions are common to every path: the plan must be `STAGE_TESTING`,
    the test session named by `active_stage_test_id` must be `FINALIZED`, and the acting
    `X-User-ID` must differ from that session's `administered_by_staff_id` or the
    decision is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/stage_decision_by_the_administering_coach_is_rejected
    """
    _athlete, staff, _coach_headers, _injury, plan, stage_test = (
        setup_plan_at_stage_testing(
            athlete_overrides={"full_name": "SoD Athlete",
                               "date_of_birth": "2009-02-02"},
            coach_name="Coach And Provider", target_stage_count=3))
    assert stage_test["administered_by_staff_id"] == staff["id"]
    assert stage_test["status"] == "FINALIZED"

    validate_error(
        api.record_stage_decision(plan["id"], {"decision": "FAIL"},
                                  make_medical_provider_headers(staff["id"])),
        "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    unchanged = fetch_rts_plan(plan["id"])
    assert unchanged["status"] == "STAGE_TESTING"
    assert unchanged["current_stage"] == 1
    assert unchanged["stage_attempts"] == 0
    assert unchanged["total_failed_attempts"] == 0
    assert unchanged["active_stage_test_id"] == stage_test["id"]
