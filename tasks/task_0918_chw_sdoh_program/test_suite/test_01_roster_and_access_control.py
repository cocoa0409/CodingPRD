"""The program roster, request authentication, role authorization and the
identifier-resolution rungs of the validation ladder."""

from test_helpers import (
    ApiErrorId,
    assert_patient,
    assert_same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.constants import SERVER_DEFAULT_CLOCK_UTC, UNKNOWN_UUID
from test_helpers.factories import (
    create_criterion_payload,
    create_patient_payload,
)
from test_helpers.test_users import (
    BILLING_SPECIALIST,
    NO_AUTH_HEADERS,
    PROGRAM_ADMIN,
    SUPERVISOR,
    make_chw_headers,
    make_partner_headers,
)


def test_new_patient_carries_every_declared_default(api):
    """PRD §3.1: "A newly created patient starts with `enrollment_status` of
    `PROSPECTIVE`, `gate_status` of `OPEN`, `risk_tier` of `NONE`, `risk_score`
    of 0, `risk_tier_effective_at` of null, `gate_reason` of null,
    `unfulfilled_referral_count` of 0 and `version` 1."
    PRD §3.1: "`program_enrollments` is an array of non-empty uppercase program
    codes the patient already participates in, such as SNAP, WIC or MEDICAID,
    and defaults to an empty array."
    PRD §3.1: "`child_in_household` is a boolean, false by default, recording
    whether a child under eighteen lives in the household."

    Design: Corner/entities/patient_creation_applies_declared_defaults_and_system_fields
    """
    worker = fx.register_worker(employee_code="C-001")
    chw_headers = make_chw_headers(worker["id"])

    payload = create_patient_payload(
        mrn="MRN-C01",
        full_name="Default Case",
        household_size=2,
        monthly_income_cents=100_000,
        residence_zip="60614",
    )
    data = validate_success(api.create_patient(payload, chw_headers), 201)

    assert_patient(data)
    assert data["enrollment_status"] == "PROSPECTIVE", (
        f"a new patient starts PROSPECTIVE, got {data['enrollment_status']}"
    )
    assert data["gate_status"] == "OPEN", (
        f"a new patient starts with gate_status OPEN, got {data['gate_status']}"
    )
    assert data["gate_reason"] is None, "gate_reason is null while the gate is OPEN"
    assert data["risk_tier"] == "NONE", (
        f"risk_tier is NONE until the first screening, got {data['risk_tier']}"
    )
    assert data["risk_score"] == 0, f"risk_score starts at 0, got {data['risk_score']}"
    assert data["risk_tier_effective_at"] is None, (
        "risk_tier_effective_at is null before the first screening"
    )
    assert data["unfulfilled_referral_count"] == 0
    assert data["program_enrollments"] == [], (
        "an omitted program_enrollments defaults to an empty array"
    )
    assert data["categorical_exclusions"] == [], (
        "an omitted categorical_exclusions defaults to an empty array"
    )
    assert data["child_in_household"] is False
    assert data["address_safety_flag"] is False
    assert data["version"] == 1, f"version begins at 1, got {data['version']}"


def test_patient_read_with_unknown_id_returns_patient_not_found(api):
    """PRD §2.5: "A patient id under the patients collection that does not
    resolve yields `ERR_PATIENT_NOT_FOUND` (404); a referral id under the
    referrals collection yields `ERR_REFERRAL_NOT_FOUND` (404); every other path
    id yields `ERR_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/entities/patient_get_with_unknown_id_returns_not_found
    """
    worker = fx.register_worker(employee_code="C-002")
    chw_headers = make_chw_headers(worker["id"])

    response = api.get_patient(UNKNOWN_UUID, chw_headers)
    validate_error(response, ApiErrorId.ERR_PATIENT_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"


def test_referral_path_id_that_does_not_resolve_returns_referral_not_found(api):
    """PRD §2.5: "A patient id under the patients collection that does not
    resolve yields `ERR_PATIENT_NOT_FOUND` (404); a referral id under the
    referrals collection yields `ERR_REFERRAL_NOT_FOUND` (404); every other path
    id yields `ERR_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/errors/referral_path_id_unknown_returns_not_found
    """
    worker = fx.register_worker(employee_code="C-062")
    chw_headers = make_chw_headers(worker["id"])

    response = api.close_referral(
        UNKNOWN_UUID,
        {"outcome_note": "Closing a referral that does not exist"},
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_REFERRAL_NOT_FOUND.value, 404)


def test_criterion_create_under_unknown_offering_returns_resource_not_found(api):
    """PRD §2.11: "For nested paths, path parameters are validated left to
    right. The eligibility-criteria routes are nested under an offering: the
    offering id is resolved first, and only then is the criterion body or the
    listing evaluated."
    PRD §2.5: "**Path resource existence** — every `{id}` segment in the URL
    resolves, checked left to right."

    Design: Corner/entities/criterion_create_under_unknown_offering_returns_not_found
    """
    fx.register_worker(employee_code="C-007")

    payload = create_criterion_payload("INCOME_BAND", max_monthly_income_cents=200_000)
    response = api.create_criterion(UNKNOWN_UUID, payload, PROGRAM_ADMIN)
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)


def test_patient_without_mrn_is_rejected_as_a_payload_failure(api):
    """PRD §3.1: "A patient record requires an `mrn` — the medical record
    number, a non-empty string unique across all patients — a `full_name`, a
    `household_size` of at least 1, a `monthly_income_cents` of at least 0, and
    a `residence_zip` of exactly five numeric characters."
    PRD §2.5: "**Payload shape and domain rules** — required fields present,
    correct JSON types, declared enum members, scalar range and cross-field
    rules, and uniqueness (`ERR_VALIDATION`, 400)."

    Design: Corner/entities/patient_missing_required_mrn_returns_invalid_request
    """
    worker = fx.register_worker(employee_code="C-004")
    chw_headers = make_chw_headers(worker["id"])

    response = api.create_patient(
        {
            "full_name": "No MRN",
            "household_size": 2,
            "monthly_income_cents": 100_000,
            "residence_zip": "60614",
        },
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    _rows, meta = validate_paginated(
        api.list_screenings(chw_headers, params={"limit": 1})
    )
    assert meta["total_count"] == 0, "the rejected payload created nothing"


def test_duplicate_mrn_is_rejected_and_leaves_the_first_row_intact(api):
    """PRD §3.1: "A patient record requires an `mrn` — the medical record
    number, a non-empty string unique across all patients — a `full_name`, a
    `household_size` of at least 1, a `monthly_income_cents` of at least 0, and
    a `residence_zip` of exactly five numeric characters."
    PRD §2.5: "**Payload shape and domain rules** — required fields present,
    correct JSON types, declared enum members, scalar range and cross-field
    rules, and uniqueness (`ERR_VALIDATION`, 400)."

    Design: Corner/entities/duplicate_mrn_second_patient_is_rejected
    """
    worker = fx.register_worker(employee_code="C-008")
    chw_headers = make_chw_headers(worker["id"])

    first = fx.add_patient(chw_headers, mrn="MRN-C08", full_name="First Row")

    response = api.create_patient(
        create_patient_payload(
            mrn="MRN-C08",
            full_name="Duplicate Row",
            household_size=3,
            monthly_income_cents=120_000,
            residence_zip="60640",
        ),
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    reread = fx.read_patient(first["id"])
    assert reread["full_name"] == "First Row", (
        "the rejected duplicate must not overwrite the row already on file"
    )


def test_referral_listing_reports_the_pagination_envelope(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object, where `total_count` is the number of rows
    matching the filters before pagination is applied and `has_more` indicates
    whether any matching row remains beyond the current page."

    Design: Corner/entities/referral_list_returns_pagination_envelope
    """
    worker, patient, chw_headers = fx.program_with_patient(employee_code="C-003")
    org, offering, _partner = fx.org_with_offering(capacity_total=5)

    fx.send_referral(chw_headers, patient["id"], offering["id"], worker["id"])
    fx.send_referral(chw_headers, patient["id"], offering["id"], worker["id"])

    response = api.list_referrals(
        chw_headers, params={"patient_id": patient["id"], "limit": 1, "offset": 0}
    )
    data, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert meta["total_count"] == 2, (
        f"total_count counts every matching row before pagination, got {meta['total_count']}"
    )
    assert meta["has_more"] is True, "a second matching row remains beyond page one"
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert len(data) == 1, f"a limit of 1 returns exactly one element, got {len(data)}"


def test_request_without_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint must carry two headers:
    `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's
    role. If either header is missing or empty, or if `X-User-Role` is not one
    of the five declared role names, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/request_missing_headers_returns_unauthenticated
    """
    fx.register_worker(employee_code="C-030")

    response = api.create_patient(
        create_patient_payload(mrn="MRN-C30", full_name="No Headers"),
        NO_AUTH_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_chw_cannot_place_a_records_hold(api):
    """PRD §3.1: "A `Supervisor` — and only a `Supervisor` — manages the
    records-hold axis, supplying an `action` of either `PLACE` or `RELEASE`
    together with an optional `reason`."
    PRD §2.1: "Once a caller is authenticated, the server checks that the
    caller's role appears in the authorized-role list declared for the target
    endpoint in §4; a caller whose role is absent from that list is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/validations/chw_cannot_place_records_hold
    """
    worker = fx.register_worker(employee_code="C-031")
    chw_headers = make_chw_headers(worker["id"])
    patient = fx.add_patient(chw_headers, mrn="MRN-C31", full_name="Role Case")

    response = api.records_hold(
        patient["id"], {"action": "PLACE", "reason": "Attempted by a CHW"}, chw_headers
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    reread = fx.read_patient(patient["id"])
    assert reread["gate_status"] == "OPEN", "the refused request placed no hold"
    assert reread["gate_reason"] is None


def test_peer_roles_cannot_cross_into_each_others_exclusive_operations(api):
    """PRD §2.1: "Once a caller is authenticated, the server checks that the
    caller's role appears in the authorized-role list declared for the target
    endpoint in §4; a caller whose role is absent from that list is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "A `BillingSpecialist` never creates, submits or voids an
    encounter — a `CHW` creates and submits encounters, a `Supervisor` voids
    them, and a `BillingSpecialist` funds them."
    PRD §3.10: "A `Supervisor`, `ProgramAdmin` or `BillingSpecialist` requests a
    derived program summary for a `service_month` under a `denominator_basis` of
    either `ENROLLED_ONLY` or `EVER_ENROLLED`."
    PRD §3.5: "Along the documentation axis, the assigned worker attests the
    visit by supplying a `visit_note`."

    Design: Corner/rbac/peer_roles_cannot_cross_into_each_others_exclusive_operations
    """
    worker, patient, chw_headers = fx.program_with_patient(employee_code="C-063")
    org, partner_headers = fx.register_org()
    visit = fx.completed_visit(chw_headers, patient["id"], worker["id"])

    billing_attempt = api.create_encounter(
        {
            "patient_id": patient["id"],
            "chw_id": worker["id"],
            "encounter_date": "2026-06-02",
            "direct_minutes": 60,
            "indirect_minutes": 0,
            "travel_minutes": 0,
            "documentation_minutes": 0,
        },
        BILLING_SPECIALIST,
    )
    validate_error(billing_attempt, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    partner_attempt = api.program_summary(
        make_partner_headers(org["id"]),
        params={"service_month": "2026-06", "denominator_basis": "ENROLLED_ONLY"},
    )
    validate_error(partner_attempt, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    admin_attempt = api.attest_home_visit(
        visit["id"], {"visit_note": "Attempted by an administrator"}, PROGRAM_ADMIN
    )
    validate_error(admin_attempt, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    _rows, meta = validate_paginated(
        api.list_encounters(chw_headers, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0, "the refused encounter was never created"
    assert fx.read_home_visit(visit["id"])["documentation_status"] == "DRAFT", (
        "the refused attestation left the documentation axis in DRAFT"
    )


def test_patient_version_advances_by_one_on_every_mutation(api):
    """PRD §2.4: "`version` begins at 1 when a row is created and increments by
    exactly 1 on every mutation of that row, including mutations applied to it
    by a cascade fired from a different entity's operation; `updated_at` is
    refreshed on the same occasions."
    PRD §3.1: "`PLACE` requires `gate_status` to be `OPEN`, moves it to
    `RECORDS_HOLD`, writes the supplied reason into `gate_reason`, and
    increments the patient's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/patient_version_increments_on_every_mutation
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    worker = fx.register_worker(employee_code="C-064")
    chw_headers = make_chw_headers(worker["id"])
    created = fx.add_patient(chw_headers, mrn="MRN-C64", full_name="Version Case")
    assert created["version"] == 1, f"creation mints version 1, got {created['version']}"

    enrolled = validate_success(
        api.update_patient(created["id"], {"enrollment_action": "ENROLL"}, SUPERVISOR)
    )
    assert enrolled["version"] == 2, (
        f"the enrolment PATCH takes version to 2, got {enrolled['version']}"
    )

    held = validate_success(
        api.records_hold(
            created["id"], {"action": "PLACE", "reason": "Consent withdrawn"}, SUPERVISOR
        )
    )
    assert held["version"] == 3, (
        f"placing the hold takes version to 3, got {held['version']}"
    )

    released = validate_success(
        api.records_hold(created["id"], {"action": "RELEASE"}, SUPERVISOR)
    )
    assert released["version"] == 4, (
        f"releasing the hold takes version to 4, got {released['version']}"
    )
    assert released["gate_status"] == "OPEN"
    assert released["gate_reason"] is None
    assert released["enrollment_status"] == "ENROLLED"


def test_logical_clock_starts_at_the_declared_startup_instant(api):
    """PRD §2.4: "Before any caller sets it, the logical clock reads exactly
    `2026-05-01T00:00:00Z`, and it must never fall back to the machine's real
    time."
    PRD §3.10: "Every escalation, however it arises, is born at `status`
    `OPEN_TIER_1` with `current_tier` 1, `promotion_count` 0,
    `acknowledged_by_user_id` null, `resolution_reason` null, `tier_entered_at`
    set to the current logical clock and `ack_deadline_at` computed from that
    instant."
    PRD §3.10: "An escalation's acknowledgement deadline is `tier_entered_at`
    plus the hours its tier allows: 48 hours at tier 1, 24 hours at tier 2, and
    8 hours at tier 3."

    Design: Corner/endpoints/logical_clock_default_is_the_declared_startup_instant
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock=None, employee_code="C-061"
    )

    data = validate_success(
        api.create_escalation(
            {"patient_id": patient["id"], "note": "Opened against the default clock"},
            chw_headers,
        ),
        201,
    )

    assert_same_instant(
        data["tier_entered_at"], SERVER_DEFAULT_CLOCK_UTC, "escalation.tier_entered_at"
    )
    assert_same_instant(
        data["ack_deadline_at"], "2026-05-03T00:00:00Z", "escalation.ack_deadline_at"
    )
    assert data["status"] == "OPEN_TIER_1"
    assert data["current_tier"] == 1
    assert data["promotion_count"] == 0
