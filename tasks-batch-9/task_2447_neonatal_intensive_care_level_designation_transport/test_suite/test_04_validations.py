"""Refusal semantics of the Neonatal Network API.

Covers the authentication and unit-scope rules of PRD §2.1, the optimistic
concurrency rule of §2.6, the numbered rejection ladder and the per-identifier
path-resolution paragraph of §2.10, and the rules those refusals are graded
against: the acceptance gates, the maternal transfer preference and the bed
ledger of §2.8 and §3.4, the designation scoring and one-open-review rule of
§3.2, and the surveillance period rule of §3.9.

The server is restarted before every test, so each test builds all of its own
preconditions through the documented endpoints.
"""

from datetime import datetime

from test_helpers import (
    CLOCK_START,
    NON_EXISTENT_UUID,
    ApiErrorId,
    UserRole,
    assert_bed_reservation,
    assert_close,
    assert_referral,
    assert_unit_counts,
    build_user_headers,
    factories,
    fixtures,
    make_intake_neonatologist_headers,
    make_unit_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _same_instant(actual, expected):
    """Compare a returned instant with the instant the PRD names, independently of
    the three fractional-second digits every timestamp is rendered with."""
    assert actual is not None, f"expected the instant {expected}, got null"
    parsed_actual = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    parsed_expected = datetime.fromisoformat(expected.replace("Z", "+00:00"))
    assert parsed_actual == parsed_expected, f"expected the instant {expected}, got {actual}"


def _bare_network():
    """The pinned clock, the three level standards and one registered unit that
    holds no credentials and no equipment."""
    return fixtures.setup_network(with_unit_b=False, credentials=(), equipment=())


# ---------------------------------------------------------------------------
# Authentication and role authorization (priority 1 and 2)
# ---------------------------------------------------------------------------


def test_requests_missing_either_auth_header_are_unauthenticated(api):
    """PRD §2.1: "If either header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."

    Design: Corner/validations/unauthenticated_and_wrong_role_requests_are_rejected
    """
    env = _bare_network()
    unit_id = env["unit_a_id"]

    empty_role = build_user_headers("net-1", "")
    validate_error(api.get_nicu_unit(unit_id, empty_role), ApiErrorId.UNAUTHENTICATED)

    empty_user = build_user_headers("", UserRole.NETWORK_ADMIN.value)
    validate_error(api.get_nicu_unit(unit_id, empty_user), ApiErrorId.UNAUTHENTICATED)


def test_role_not_listed_against_the_endpoint_writes_nothing(api):
    """PRD §2.1: "If both headers are present but the value of `X-User-Role` is not one of the roles listed against the endpoint in §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/validations/unauthenticated_and_wrong_role_requests_are_rejected
    """
    env = _bare_network()

    nurse_built_unit = factories.community_unit_payload(
        name="Nurse Built Unit", staffed_bed_target=2
    )
    validate_error(
        api.create_nicu_unit(nurse_built_unit, env["nurse"]), ApiErrorId.ROLE_NOT_PERMITTED
    )

    level_iv = factories.designation_standard_payload("LEVEL_IV")
    validate_error(
        api.create_designation_standard(level_iv, env["dir_a"]), ApiErrorId.ROLE_NOT_PERMITTED
    )

    _, unit_meta = validate_paginated(api.list_nicu_units(env["admin"]))
    assert unit_meta["total_count"] == 1
    _, standard_meta = validate_paginated(api.list_designation_standards(env["admin"]))
    assert standard_meta["total_count"] == 3


# ---------------------------------------------------------------------------
# Unit scope (priority 4)
# ---------------------------------------------------------------------------


def test_foreign_unit_director_cannot_edit_another_units_capacity(api, network):
    """PRD §2.10: "Unit scope: for the three unit-scoped roles, the unit parsed from `X-User-ID` must match the unit the operation acts on as described in §2.1, else `ERR_UNIT_SCOPE_VIOLATION` (403)."

    PRD §2.1: "A mismatch is rejected with `ERR_UNIT_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/validations/unit_scoped_caller_cannot_act_for_another_unit
    """
    env = network
    before = fixtures.read_unit(env)
    foreign_director = make_unit_director_headers(env["unit_b_id"])

    # The quoted version is perfectly fresh, so only the scope check can refuse this.
    refused = api.patch_nicu_unit(
        env["unit_a_id"],
        factories.unit_patch_payload(before["version"], staffed_bed_target=99),
        foreign_director,
    )
    validate_error(refused, ApiErrorId.UNIT_SCOPE_VIOLATION)

    after = fixtures.read_unit(env)
    assert after["staffed_bed_target"] == before["staffed_bed_target"]
    assert after["version"] == before["version"]


def test_intake_neonatologist_of_another_unit_cannot_accept_the_referral(api, network):
    """PRD §2.1: "The unit portion is what ownership checks compare against: for endpoints addressed at a unit, it must equal the unit named in the path; for intake actions on a referral, it must equal that referral's `receiving_unit_id`; for referral creation and referral withdrawal, it must equal the referral's `referring_unit_id`; and for bedside or intake actions on an admission, it must equal that admission's `unit_id`."

    PRD §2.1: "A mismatch is rejected with `ERR_UNIT_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/validations/unit_scoped_caller_cannot_act_for_another_unit
    """
    env = network
    referral = fixtures.create_referral(env)
    fresh_version = fixtures.read_unit_version(env)
    foreign_intake = make_intake_neonatologist_headers(env["unit_b_id"])

    refused = api.accept_referral(
        referral["id"], factories.accept_referral_payload(fresh_version), foreign_intake
    )
    validate_error(refused, ApiErrorId.UNIT_SCOPE_VIOLATION)

    assert fixtures.read_referral(env, referral["id"])["status"] == "PENDING"
    assert fixtures.read_unit_version(env) == fresh_version


# ---------------------------------------------------------------------------
# Optimistic concurrency ahead of own state (priority 7 before 8)
# ---------------------------------------------------------------------------


def test_stale_unit_version_outranks_the_already_accepted_referral(api, network):
    """PRD §2.6: "Where a version field is declared, it is checked before any state or business rule is evaluated, so that a caller working from a stale read is told to re-read rather than being told its stale decision was illegal."

    PRD §2.6: "If any other writer has advanced that unit's `version` since the client read it, the acceptance is rejected with `ERR_UNIT_VERSION_CONFLICT` (HTTP 412) and no reservation is created."

    Design: Corner/validations/occ_conflict_outranks_the_own_state_conflict
    """
    env = network
    referral = fixtures.create_referral(env)
    stale_version = fixtures.read_unit_version(env)
    assert stale_version == 1
    fixtures.accept_referral(env, referral["id"], expected_unit_version=stale_version)

    replay = api.accept_referral(
        referral["id"], factories.accept_referral_payload(stale_version), env["intake_a"]
    )
    validate_error(replay, ApiErrorId.UNIT_VERSION_CONFLICT)

    unit = fixtures.read_unit(env)
    assert unit["version"] == 2
    assert_unit_counts(unit, occupied=0, held=1, available=3)


def test_fresh_unit_version_exposes_the_referrals_own_state_conflict(api, network):
    """PRD §2.10: "Own state: the entity's own status must permit the trigger, including terminal-state lockdown and rejection of a repeated trigger, else `ERR_INVALID_STATE` (409)."

    PRD §2.10: "Checks are evaluated in the following fixed order, and the first failure is returned immediately."

    Design: Corner/validations/occ_conflict_outranks_the_own_state_conflict
    """
    env = network
    referral = fixtures.create_referral(env)
    fixtures.accept_referral(env, referral["id"])
    fresh_version = fixtures.read_unit_version(env)
    assert fresh_version == 2

    replay = api.accept_referral(
        referral["id"], factories.accept_referral_payload(fresh_version), env["intake_a"]
    )
    validate_error(replay, ApiErrorId.INVALID_STATE)

    unit = fixtures.read_unit(env)
    assert unit["version"] == 2
    assert_unit_counts(unit, occupied=0, held=1, available=3)


# ---------------------------------------------------------------------------
# Request schema ahead of body reference existence (priority 5 before 6)
# ---------------------------------------------------------------------------


def test_inverted_escalation_window_is_refused_as_a_schema_fault(api):
    """PRD §2.10: "Request schema: required fields present, types correct, enum values in range, numbers inside their declared bounds, `period_end` strictly after `period_start`, `planned_return_at` strictly after `depart_at`, `effective_to` strictly after `effective_from`, `limit` between 1 and 100 inclusive and `offset` at least 0 — else `ERR_INVALID_REQUEST` (400)."

    PRD §2.10: "Checks are evaluated in the following fixed order, and the first failure is returned immediately."

    Design: Corner/validations/schema_check_runs_before_body_reference_existence
    """
    env = _bare_network()

    # The body also names a unit that cannot resolve; the schema fault is the answer.
    payload = factories.surge_escalation_payload(
        NON_EXISTENT_UUID,
        requested_beds=2,
        effective_from="2026-08-03T00:00:00Z",
        effective_to="2026-08-02T00:00:00Z",
    )
    validate_error(api.create_surge_escalation(payload, env["dir_a"]), ApiErrorId.INVALID_REQUEST)

    _, meta = validate_paginated(api.list_surge_escalations(env["admin"]))
    assert meta["total_count"] == 0


def test_unresolvable_body_unit_id_surfaces_once_the_schema_is_clean(api):
    """PRD §2.10: "Body existence: every `id` supplied in the request body must resolve — `unit_id`, `referral_id`, `admission_id`, `isolette_asset_id`, `clinic_unit_id`, `reservation_id` — else the matching not-found code (404)."

    PRD §2.10: "A `unit_id` — and equally a `clinic_unit_id`, a `referring_unit_id` or a `receiving_unit_id` — that does not resolve yields `ERR_UNIT_NOT_FOUND`."

    Design: Corner/validations/schema_check_runs_before_body_reference_existence
    """
    env = _bare_network()

    payload = factories.surge_escalation_payload(
        NON_EXISTENT_UUID,
        requested_beds=2,
        effective_from="2026-08-02T00:00:00Z",
        effective_to="2026-08-03T00:00:00Z",
    )
    validate_error(api.create_surge_escalation(payload, env["dir_a"]), ApiErrorId.UNIT_NOT_FOUND)

    _, meta = validate_paginated(api.list_surge_escalations(env["admin"]))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Role authorization ahead of path existence (priority 2 before 3)
# ---------------------------------------------------------------------------


def test_wrong_role_is_refused_without_resolving_the_path(api):
    """PRD §2.10: "Role authorization: `X-User-Role` must be one of the roles listed against the endpoint, else `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD §2.10: "Checks are evaluated in the following fixed order, and the first failure is returned immediately."

    Design: Corner/validations/role_check_runs_before_path_existence
    """
    env = fixtures.setup_network(
        standard_levels=(), with_unit_b=False, credentials=(), equipment=()
    )

    # No review exists at all, yet the authorization boundary answers first.
    refused = api.verify_designation_review(NON_EXISTENT_UUID, {}, env["ref_a"])
    validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED)


def test_permitted_role_reading_a_missing_review_id_gets_review_not_found(api):
    """PRD §2.10: "Path existence: every `id` appearing in the URL path must resolve to a stored row, resolved strictly left to right, else the matching not-found code for that entity (404)."

    PRD §2.10: "A `standard_id` yields `ERR_STANDARD_NOT_FOUND`; a `credential_id` yields `ERR_CREDENTIAL_NOT_FOUND`; an `asset_id`, or an `isolette_asset_id` supplied in a body, yields `ERR_ASSET_NOT_FOUND`; a `review_id` yields `ERR_REVIEW_NOT_FOUND`; a `referral_id` yields `ERR_REFERRAL_NOT_FOUND`; a `reservation_id` yields `ERR_RESERVATION_NOT_FOUND`; a `run_id` yields `ERR_RUN_NOT_FOUND`; an `admission_id`, including a `source_admission_id` or a `back_transfer_source_admission_id`, yields `ERR_ADMISSION_NOT_FOUND`; a `batch_id` yields `ERR_MILK_BATCH_NOT_FOUND`; an `escalation_id` yields `ERR_ESCALATION_NOT_FOUND`; a `report_id` yields `ERR_REPORT_NOT_FOUND`; and an `enrollment_id` yields `ERR_ENROLLMENT_NOT_FOUND`."

    Design: Corner/validations/role_check_runs_before_path_existence
    """
    env = fixtures.setup_network(
        standard_levels=(), with_unit_b=False, credentials=(), equipment=()
    )

    refused = api.verify_designation_review(NON_EXISTENT_UUID, {}, env["admin"])
    validate_error(refused, ApiErrorId.REVIEW_NOT_FOUND)


# ---------------------------------------------------------------------------
# Capacity, evaluated last (priority 15)
# ---------------------------------------------------------------------------


def test_fifth_acceptance_is_refused_once_the_bed_ledger_is_exhausted(api, network):
    """PRD §3.4: "The unit's `available_bed_count` must be at least 1, or the acceptance is refused with `ERR_NO_BED_AVAILABLE`."

    PRD §2.8: "And `available_bed_count` is the base staffed bed target plus the escalation bed count, minus the occupied bed count, minus the held bed count."

    Design: Corner/validations/aggregate_bed_capacity_refuses_the_fifth_hold
    """
    env = network
    for case_reference in ("CASE-N1", "CASE-N2", "CASE-F3", "CASE-F4"):
        fixtures.hold_bed(env, case_reference=case_reference)

    fifth = fixtures.create_referral(env, case_reference="CASE-F5")
    fresh_version = fixtures.read_unit_version(env)
    assert fresh_version == 5

    refused = api.accept_referral(
        fifth["id"], factories.accept_referral_payload(fresh_version), env["intake_a"]
    )
    validate_error(refused, ApiErrorId.NO_BED_AVAILABLE)

    still_pending = fixtures.read_referral(env, fifth["id"])
    assert still_pending["status"] == "PENDING"
    assert still_pending["reservation_id"] is None
    _, reservation_meta = validate_paginated(
        api.list_bed_reservations(env["admin"], params={"referral_id": fifth["id"]})
    )
    assert reservation_meta["total_count"] == 0

    unit = fixtures.read_unit(env)
    assert unit["version"] == fresh_version
    assert_unit_counts(unit, held=4, available=0, posture="CLOSED")


def test_deferral_parks_the_case_the_ledger_could_not_take(api, network):
    """PRD §3.4: "Deferral moves a referral `PENDING → DEFERRED`, is permitted only when the unit's `available_bed_count` is at or below zero, records `decision_reason` `NO_BED`, and causes the unit's `deferral_queue_depth` to be re-derived."

    Design: Corner/validations/aggregate_bed_capacity_refuses_the_fifth_hold
    """
    env = network
    for case_reference in ("CASE-N1", "CASE-N2", "CASE-F3", "CASE-F4"):
        fixtures.hold_bed(env, case_reference=case_reference)

    fifth = fixtures.create_referral(env, case_reference="CASE-F5")
    deferred = validate_success(api.defer_referral(fifth["id"], {}, env["intake_a"]))
    assert deferred["status"] == "DEFERRED"
    assert deferred["decision_reason"] == "NO_BED"

    unit = fixtures.read_unit(env)
    assert unit["deferral_queue_depth"] == 1
    assert_unit_counts(unit, held=4, available=0, posture="CLOSED")


# ---------------------------------------------------------------------------
# The community volume rule
# ---------------------------------------------------------------------------


def test_regional_centre_volume_subscore_uses_the_full_minimum(api, network):
    """PRD §3.2: "For volume, the effective minimum is the standard's `min_annual_volume` for a unit whose `hospital_type` is `REGIONAL_CENTER`, and half of that figure for a `COMMUNITY` unit; `volume_subscore` is 100 multiplied by the lower of 1.0 and the unit's `annual_admission_volume` divided by that effective minimum, rounded half up to two decimals."

    PRD §3.2: "A permitted submission increments `submission_round` by one, stamps `assessment_at` with the current clock instant, records the caller's `X-User-ID` as `submitted_by_user_id`, and freezes `required_nurse_count`, `staffing_subscore`, `equipment_subscore`, `volume_subscore` and `compliance_score` onto the review as they stand at that instant."

    Design: Corner/validations/community_volume_half_rule_applies_only_to_community_units
    """
    env = network
    review = fixtures.open_review(env, requested_level="LEVEL_III", assigned_nurse_count=2)

    submitted = validate_success(
        api.submit_designation_review(review["id"], {}, env["dir_a"])
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_round"] == 1
    assert_close(submitted["volume_subscore"], 80.00)


def test_community_unit_volume_minimum_is_halved(api, network):
    """PRD §3.2: "For volume, the effective minimum is the standard's `min_annual_volume` for a unit whose `hospital_type` is `REGIONAL_CENTER`, and half of that figure for a `COMMUNITY` unit; `volume_subscore` is 100 multiplied by the lower of 1.0 and the unit's `annual_admission_volume` divided by that effective minimum, rounded half up to two decimals."

    PRD §3.2: "`compliance_score` is then 0.45 of the staffing subscore plus 0.35 of the equipment subscore plus 0.20 of the volume subscore, rounded half up to two decimals."

    Design: Corner/validations/community_volume_half_rule_applies_only_to_community_units
    """
    env = network
    community_director = make_unit_director_headers(env["unit_b_id"])
    review = fixtures.open_review(
        env, unit_id=env["unit_b_id"], requested_level="LEVEL_II", assigned_nurse_count=1
    )

    submitted = validate_success(
        api.submit_designation_review(review["id"], {}, community_director)
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_round"] == 1
    assert_close(submitted["volume_subscore"], 100.00)
    assert_close(submitted["staffing_subscore"], 0.00)
    assert_close(submitted["equipment_subscore"], 0.00)
    assert_close(submitted["compliance_score"], 20.00)


# ---------------------------------------------------------------------------
# Surveillance periods
# ---------------------------------------------------------------------------


def test_period_reaching_back_before_the_unit_existed_is_refused(api):
    """PRD §3.9: "A period that begins before the unit itself was created is refused with `ERR_PERIOD_INVALID`."

    Design: Corner/validations/surveillance_period_before_the_unit_existed_is_refused
    """
    env = _bare_network()

    payload = factories.surveillance_report_payload(
        env["unit_a_id"],
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-08-01T00:00:00Z",
        reported_patient_days=10,
        reported_central_line_days=4,
    )
    validate_error(api.create_surveillance_report(payload, env["dir_a"]), ApiErrorId.PERIOD_INVALID)

    _, meta = validate_paginated(api.list_surveillance_reports(env["admin"]))
    assert meta["total_count"] == 0


def test_inverted_surveillance_period_is_a_schema_fault(api):
    """PRD §2.10: "Request schema: required fields present, types correct, enum values in range, numbers inside their declared bounds, `period_end` strictly after `period_start`, `planned_return_at` strictly after `depart_at`, `effective_to` strictly after `effective_from`, `limit` between 1 and 100 inclusive and `offset` at least 0 — else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/validations/surveillance_period_before_the_unit_existed_is_refused
    """
    env = _bare_network()

    payload = factories.surveillance_report_payload(
        env["unit_a_id"],
        period_start="2026-08-31T00:00:00Z",
        period_end="2026-08-01T00:00:00Z",
        reported_patient_days=10,
        reported_central_line_days=4,
    )
    validate_error(
        api.create_surveillance_report(payload, env["dir_a"]), ApiErrorId.INVALID_REQUEST
    )

    _, meta = validate_paginated(api.list_surveillance_reports(env["admin"]))
    assert meta["total_count"] == 0


def test_period_starting_exactly_at_the_units_creation_is_allowed(api):
    """PRD §3.9: "A period that begins before the unit itself was created is refused with `ERR_PERIOD_INVALID`."

    PRD §3.9: "The report opens at status `DRAFT`, and reports may be listed filtered by `unit_id`, `status`, `network_benchmark_flag` and `variant_applied`."

    Design: Corner/validations/surveillance_period_before_the_unit_existed_is_refused
    """
    env = _bare_network()
    unit = fixtures.read_unit(env)

    payload = factories.surveillance_report_payload(
        env["unit_a_id"],
        period_start=CLOCK_START,
        period_end="2026-08-31T00:00:00Z",
        reported_patient_days=10,
        reported_central_line_days=4,
    )
    report = validate_success(api.create_surveillance_report(payload, env["dir_a"]), 201)
    assert report["status"] == "DRAFT"
    _same_instant(report["period_start"], unit["created_at"])

    _, meta = validate_paginated(api.list_surveillance_reports(env["admin"]))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# One open designation review per unit
# ---------------------------------------------------------------------------


def test_second_review_is_refused_while_the_first_is_draft(api):
    """PRD §3.2: "Only one review may be open per unit at a time: if the unit already has a review in `DRAFT`, `SUBMITTED`, `RETURNED` or `VERIFIED`, the attempt is refused with `ERR_REVIEW_ALREADY_OPEN`."

    Design: Corner/validations/second_open_review_for_the_same_unit_is_refused
    """
    env = _bare_network()
    first = fixtures.open_review(env, requested_level="LEVEL_III", assigned_nurse_count=2)
    assert first["status"] == "DRAFT"

    second = factories.designation_review_payload(
        env["unit_a_id"], requested_level="LEVEL_II", assigned_nurse_count=1
    )
    validate_error(
        api.create_designation_review(second, env["dir_a"]), ApiErrorId.REVIEW_ALREADY_OPEN
    )

    _, meta = validate_paginated(
        api.list_designation_reviews(env["admin"], params={"unit_id": env["unit_a_id"]})
    )
    assert meta["total_count"] == 1


def test_second_review_is_refused_while_the_first_is_submitted(api):
    """PRD §3.2: "Only one review may be open per unit at a time: if the unit already has a review in `DRAFT`, `SUBMITTED`, `RETURNED` or `VERIFIED`, the attempt is refused with `ERR_REVIEW_ALREADY_OPEN`."

    Design: Corner/validations/second_open_review_for_the_same_unit_is_refused
    """
    env = _bare_network()
    first = fixtures.open_review(env, requested_level="LEVEL_III", assigned_nurse_count=2)
    submitted = fixtures.submit_review(env, first["id"])
    assert submitted["status"] == "SUBMITTED"

    second = factories.designation_review_payload(
        env["unit_a_id"], requested_level="LEVEL_II", assigned_nurse_count=1
    )
    validate_error(
        api.create_designation_review(second, env["dir_a"]), ApiErrorId.REVIEW_ALREADY_OPEN
    )

    _, meta = validate_paginated(
        api.list_designation_reviews(env["admin"], params={"unit_id": env["unit_a_id"]})
    )
    assert meta["total_count"] == 1


def test_a_new_review_is_allowed_once_the_first_one_is_denied(api):
    """PRD §3.2: "From `SUBMITTED`, the same certification call instead moves the review `SUBMITTED → DENIED` when `compliance_score` is strictly below the standard's `conditional_floor_score`: `denial_basis` becomes `SCORE_BELOW_FLOOR`, `outcome_level` stays null, and the caller must differ from `submitted_by_user_id`."

    PRD §3.2: "Only one review may be open per unit at a time: if the unit already has a review in `DRAFT`, `SUBMITTED`, `RETURNED` or `VERIFIED`, the attempt is refused with `ERR_REVIEW_ALREADY_OPEN`."

    Design: Corner/validations/second_open_review_for_the_same_unit_is_refused
    """
    env = _bare_network()
    first = fixtures.open_review(env, requested_level="LEVEL_III", assigned_nurse_count=2)
    submitted = fixtures.submit_review(env, first["id"])
    assert_close(submitted["compliance_score"], 16.00)

    denied = validate_success(api.certify_designation_review(first["id"], {}, env["admin"]))
    assert denied["status"] == "DENIED"
    assert denied["denial_basis"] == "SCORE_BELOW_FLOOR"
    assert denied["outcome_level"] is None

    reopened = validate_success(
        api.create_designation_review(
            factories.designation_review_payload(
                env["unit_a_id"], requested_level="LEVEL_II", assigned_nurse_count=1
            ),
            env["dir_a"],
        ),
        201,
    )
    assert reopened["status"] == "DRAFT"

    _, meta = validate_paginated(
        api.list_designation_reviews(env["admin"], params={"unit_id": env["unit_a_id"]})
    )
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# The maternal transfer preference on the last bed
# ---------------------------------------------------------------------------


def _one_bed_unit_with_two_waiting_cases(env):
    """Shrink unit A to a single staffed bed, then queue a maternal antenatal case
    and a lower-priority inbound case at it."""
    fixtures.patch_unit(env, headers=env["dir_a"], staffed_bed_target=1)
    maternal = fixtures.create_referral(
        env,
        case_reference="CASE-MAT1",
        referral_kind="MATERNAL_ANTENATAL",
        gestational_age_weeks=30.0,
        birth_weight_grams=1300,
        support_modality="ROOM_AIR",
    )
    inbound = fixtures.create_referral(env, case_reference="CASE-N1")
    return maternal, inbound


def test_antenatal_case_is_scored_on_its_anticipated_need(api, network):
    """PRD §3.3: "`level_basis` records which variant drove the answer: it is `ANTICIPATED_NEED` when `anticipated_need_level` outranks `current_support_level`, and `CURRENT_SUPPORT` otherwise — including when the two are equal."

    PRD §3.3: "`maternal_transfer_preferred` is true exactly when `referral_kind` is `MATERNAL_ANTENATAL` and `required_level` ranks at `LEVEL_III` or above."

    PRD §3.3: "An antenatal `LEVEL_III` case at 30.0 weeks and 1300 grams scores 78.75; an inbound `LEVEL_III` case at 29.0 weeks and 1200 grams scores 71.25, as does an inbound `LEVEL_III` case at 30.0 weeks and 1250 grams — ties are real and are broken by the rules in §3.4."

    Design: Corner/validations/maternal_transfer_preference_reserves_the_last_bed
    """
    env = network
    maternal, inbound = _one_bed_unit_with_two_waiting_cases(env)

    assert_referral(maternal)
    assert maternal["current_support_level"] == "LEVEL_I"
    assert maternal["anticipated_need_level"] == "LEVEL_III"
    assert maternal["required_level"] == "LEVEL_III"
    assert maternal["level_basis"] == "ANTICIPATED_NEED"
    assert maternal["maternal_transfer_preferred"] is True
    assert_close(maternal["triage_priority"], 78.75)

    assert_referral(inbound)
    assert_close(inbound["triage_priority"], 71.25)


def test_last_free_bed_is_withheld_from_the_lower_priority_inbound_case(api, network):
    """PRD §3.4: "When an acceptance would consume the last free bed — meaning `available_bed_count` immediately before the operation is exactly 1 — and the referral being accepted is not of kind `MATERNAL_ANTENATAL`, the unit must first look for a blocked maternal transfer: any referral at the same receiving unit whose status is `PENDING` or `DEFERRED`, whose `referral_kind` is `MATERNAL_ANTENATAL`, whose `required_level` ranks at or below the unit's `effective_level`, and whose `triage_priority` is **strictly greater** than the incoming referral's."

    PRD §3.4: "If such a referral exists the acceptance is refused with `ERR_MATERNAL_TRANSFER_PREFERENCE`."

    Design: Corner/validations/maternal_transfer_preference_reserves_the_last_bed
    """
    env = network
    _, inbound = _one_bed_unit_with_two_waiting_cases(env)
    quoted_version = fixtures.read_unit_version(env)
    assert quoted_version == 2

    refused = api.accept_referral(
        inbound["id"], factories.accept_referral_payload(quoted_version), env["intake_a"]
    )
    validate_error(refused, ApiErrorId.MATERNAL_TRANSFER_PREFERENCE)

    assert fixtures.read_referral(env, inbound["id"])["status"] == "PENDING"
    unit = fixtures.read_unit(env)
    assert unit["version"] == quoted_version
    assert_unit_counts(unit, held=0, available=1)


def test_maternal_acceptance_takes_the_last_bed_on_a_twelve_hour_hold(api, network):
    """PRD §3.4: "A permitted acceptance moves the referral `PENDING → ACCEPTED` and creates a bed reservation for it, carrying the receiving unit as `unit_id` and the referral as `referral_id`, starting at status `HELD`, taking its `bed_class` from the waterfall rule of §2.8, stamping `held_at` with the current clock instant, and computing `expires_at` from the referral's kind: an antenatal hold lasts 720 minutes — twelve hours — from `held_at`, because a mother in labour needs a bed that will still be there tomorrow morning, while every other kind of hold lasts 240 minutes, four hours."

    PRD §2.8: "First, allocation is a **waterfall**: a new hold takes `bed_class` `STAFFED` while the pre-operation sum of `occupied_bed_count` and `held_bed_count` is strictly below `staffed_bed_target`, and `ESCALATION` otherwise."

    Design: Corner/validations/maternal_transfer_preference_reserves_the_last_bed
    """
    env = network
    maternal, _ = _one_bed_unit_with_two_waiting_cases(env)
    quoted_version = fixtures.read_unit_version(env)

    accepted = validate_success(
        api.accept_referral(
            maternal["id"], factories.accept_referral_payload(quoted_version), env["intake_a"]
        )
    )
    assert accepted["status"] == "ACCEPTED"

    reservation = fixtures.read_reservation(env, accepted["reservation_id"])
    assert_bed_reservation(reservation)
    assert reservation["status"] == "HELD"
    assert reservation["bed_class"] == "STAFFED"
    _same_instant(reservation["held_at"], CLOCK_START)
    _same_instant(reservation["expires_at"], "2026-08-01T12:00:00Z")

    unit = fixtures.read_unit(env)
    assert unit["version"] == 3
    assert_unit_counts(unit, held=1, available=0)


# ---------------------------------------------------------------------------
# The acceptance that passes every gate
# ---------------------------------------------------------------------------


def test_acceptance_passing_every_gate_returns_the_hold_and_the_new_ledger(api, network):
    """PRD §3.4: "A permitted acceptance moves the referral `PENDING → ACCEPTED` and creates a bed reservation for it, carrying the receiving unit as `unit_id` and the referral as `referral_id`, starting at status `HELD`, taking its `bed_class` from the waterfall rule of §2.8, stamping `held_at` with the current clock instant, and computing `expires_at` from the referral's kind: an antenatal hold lasts 720 minutes — twelve hours — from `held_at`, because a mother in labour needs a bed that will still be there tomorrow morning, while every other kind of hold lasts 240 minutes, four hours."

    PRD §2.8: "And `available_bed_count` is the base staffed bed target plus the escalation bed count, minus the occupied bed count, minus the held bed count."

    PRD §2.8: "First, allocation is a **waterfall**: a new hold takes `bed_class` `STAFFED` while the pre-operation sum of `occupied_bed_count` and `held_bed_count` is strictly below `staffed_bed_target`, and `ESCALATION` otherwise."

    Design: Corner/validations/every_gate_satisfied_lets_the_acceptance_through
    """
    env = network
    referral = fixtures.create_referral(env)
    quoted_version = fixtures.read_unit_version(env)

    accepted = validate_success(
        api.accept_referral(
            referral["id"], factories.accept_referral_payload(quoted_version), env["intake_a"]
        )
    )
    assert_referral(accepted)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["decision_reason"] is None
    assert accepted["reservation_id"] is not None

    reservation = fixtures.read_reservation(env, accepted["reservation_id"])
    assert_bed_reservation(reservation)
    assert reservation["referral_id"] == referral["id"]
    assert reservation["unit_id"] == env["unit_a_id"]
    assert reservation["status"] == "HELD"
    assert reservation["bed_class"] == "STAFFED"
    _same_instant(reservation["held_at"], CLOCK_START)
    _same_instant(reservation["expires_at"], "2026-08-01T04:00:00Z")

    unit = fixtures.read_unit(env)
    assert unit["version"] == 2
    assert unit["deferral_queue_depth"] == 0
    assert_unit_counts(unit, occupied=0, held=1, available=3, posture="OPEN")
