"""Validation and state-precondition tests (§2.1, §3.1-§3.6).

Consent-photo gating, product agreement, loyalty-program agreement,
consultation-in-use, missing-auth, idempotent transitions, and the
plan-completion / plan-cancellation guards.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_provider_headers,
    make_clinic_admin_headers,
    make_membership,
    make_patient,
    make_loyalty_account,
    make_injector,
    make_director,
    make_lot,
    sign_consent,
    make_consultation,
    complete_exam,
    make_standing_order,
    make_plan,
    activate_plan,
    setup_active_plan,
    setup_proposed_plan,
    setup_committed_session,
    setup_booked_session,
    book_session,
    plan_version,
    create_treatment_session_payload,
    create_loyalty_account_payload,
    create_provider_payload,
)


# ---------------------------------------------------------------------------
# validations
# ---------------------------------------------------------------------------
def test_book_without_consent_photo_rejected(api):
    """PRD §3.4: "The patient's `photo_consent_on_file` must be `true` (otherwise
    `ERR_CONSENT_PHOTO_REQUIRED`)." PRD §3.5: "A signed `CONSENT` photo must exist for
    the patient before a session can be booked, or booking fails with
    `ERR_CONSENT_PHOTO_REQUIRED`."

    Design: Corner/validations/book_session_without_consent_photo_returns_consent_required
    """
    sc = setup_active_plan(sign_consent_photo=False)
    payload = create_treatment_session_payload(
        sc.plan_id, sc.standing_order_id, sc.injector_id, sc.lot_id, 20, sc.plan_version)
    resp = api.create_treatment_session(payload, make_provider_headers(sc.injector_id))
    validate_error(resp, ApiErrorId.ERR_CONSENT_PHOTO_REQUIRED.value)


def test_product_mismatch_on_booking_rejected(api):
    """PRD §3.4: "The product must agree across all three sources — the standing
    order's product, the plan's product, and the chosen lot's product must be
    identical (otherwise `ERR_PRODUCT_MISMATCH`)."

    A BOTOX plan/order with a JUVEDERM lot is rejected `ERR_PRODUCT_MISMATCH` (422).

    Design: Corner/validations/product_mismatch_on_booking_returns_422
    """
    admin = make_clinic_admin_headers()
    inj = make_injector(license_number="L-PM-I")["id"]
    director = make_director(license_number="L-PM-D")["id"]
    bad_lot = make_lot(product="JUVEDERM", lot_number="LOT-PM-J")["id"]
    patient = make_patient(full_name="Pm Pat")["id"]
    sign_consent(patient, inj)
    cons = make_consultation(patient, inj)["id"]
    complete_exam(cons, inj)
    order = make_standing_order(cons, director, product="BOTOX",
                                max_units_authorized=30)["id"]
    plan = make_plan(patient, cons, inj, product="BOTOX", planned_units_per_session=20)
    activated = activate_plan(plan["id"], plan["version"], inj)
    payload = create_treatment_session_payload(
        plan["id"], order, inj, bad_lot, 20, activated["version"])
    resp = api.create_treatment_session(payload, make_provider_headers(inj))
    validate_error(resp, ApiErrorId.ERR_PRODUCT_MISMATCH.value)


def test_loyalty_program_mismatch_rejected(api):
    """PRD §3.1: "The account's program must equal the loyalty program of the
    patient's membership — that is, the `loyalty_program` on the `MembershipPackage`
    the patient's `membership_id` points to — otherwise the request is rejected with
    `ERR_LOYALTY_PROGRAM_MISMATCH`."

    Opening an ASPIRE account for an ALLE member is rejected (422).

    Design: Corner/validations/loyalty_program_mismatch_returns_422
    """
    admin = make_clinic_admin_headers()
    pkg = make_membership(tier="PLUS", member_discount_pct=0.15, loyalty_program="ALLE")
    patient = make_patient(full_name="Lm Pat", membership_id=pkg["id"])
    resp = api.create_loyalty_account(
        create_loyalty_account_payload(patient["id"], program="ASPIRE"), admin)
    validate_error(resp, ApiErrorId.ERR_LOYALTY_PROGRAM_MISMATCH.value)


def test_void_consultation_in_use_by_active_plan_rejected(api):
    """PRD §3.2: "Voiding from `EXAM_COMPLETE` to `VOID` is permitted only when no
    `TreatmentPlan` in `PROPOSED` or `ACTIVE` `status` references this consultation; if
    one does, the void is rejected with `ERR_CONSULTATION_IN_USE`."

    Design: Corner/validations/void_consultation_in_use_by_active_plan_returns_in_use
    """
    sc = setup_active_plan()
    admin = make_clinic_admin_headers()
    resp = api.void_consultation(sc.consultation_id, admin)
    validate_error(resp, ApiErrorId.ERR_CONSULTATION_IN_USE.value)


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "A request missing either header, or carrying a value the system
    cannot interpret, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
    PRD §2.8: "First, header presence and validity are checked
    (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`) ..."

    A request with no role/user headers is rejected before any other check.

    Design: Corner/validations/missing_auth_header_returns_400
    """
    resp = api.create_provider(
        create_provider_payload(full_name="No Auth", license_number="L-NA",
                                role_kind="INJECTOR"), {})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


# ---------------------------------------------------------------------------
# state_machines (remaining non-stub instances)
# ---------------------------------------------------------------------------
def test_complete_exam_twice_returns_not_draft(api):
    """PRD §3.2: "Finalizing the exam advances the consultation from `DRAFT` to
    `EXAM_COMPLETE`, which is permitted only while it is in `DRAFT` (otherwise
    `ERR_CONSULTATION_NOT_DRAFT`) ..."

    A second complete-exam on an already `EXAM_COMPLETE` consultation is rejected.

    Design: Corner/state_machines/complete_exam_twice_second_returns_not_draft
    """
    inj = make_injector(license_number="L-IDP-I")["id"]
    patient = make_patient(full_name="Idp Pat")["id"]
    cons = make_consultation(patient, inj)["id"]
    complete_exam(cons, inj)
    resp = api.complete_exam(cons, make_provider_headers(inj))
    validate_error(resp, ApiErrorId.ERR_CONSULTATION_NOT_DRAFT.value)


def test_commit_already_committed_returns_not_booked(api):
    """PRD §3.6: "Committing advances a session from `BOOKED` to `COMMITTED`. It is
    permitted only when the session is `BOOKED` (otherwise `ERR_SESSION_NOT_BOOKED`)
    ..."

    Committing an already-`COMMITTED` session is rejected `ERR_SESSION_NOT_BOOKED`.

    Design: Corner/state_machines/commit_session_from_committed_returns_not_booked
    """
    sc = setup_committed_session(member=False, list_price_per_unit_cents=1000,
                                 planned_units=20, max_units_authorized=30)
    resp = api.commit_session(sc.session_id, {}, make_provider_headers(sc.injector_id))
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_BOOKED.value)


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------
def test_complete_plan_with_open_session_rejected(api):
    """PRD §3.3: "Completing a plan advances it from `ACTIVE` to `COMPLETED`. It is
    permitted only when the plan is `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`), when
    `expected_treatment_plan_version` matches the plan's current version (otherwise
    `ERR_STALE_PLAN_VERSION`), and when no session on the plan is in `BOOKED`,
    `COMMITTED`, or `COMPLICATION_OPEN` (otherwise `ERR_OPEN_SESSIONS_EXIST`)."

    Design: Corner/errors/complete_plan_with_open_session_returns_open_sessions_exist
    """
    sc = setup_booked_session(planned_units=20, max_units_authorized=30, add_before=False)
    inj = sc.injector_id
    pv = plan_version(sc.plan_id, inj)
    resp = api.complete_plan(sc.plan_id, {"expected_treatment_plan_version": pv},
                             make_provider_headers(inj))
    validate_error(resp, ApiErrorId.ERR_OPEN_SESSIONS_EXIST.value)


def test_cancel_plan_with_committed_session_rejected(api):
    """PRD §3.3: "Cancellation, performed by a `ClinicAdmin`, applies from either
    `PROPOSED` or `ACTIVE` and moves the plan to `CANCELLED`. It is permitted only when
    the plan is in `PROPOSED` or `ACTIVE` (otherwise `ERR_PLAN_NOT_CANCELLABLE`), when
    `expected_treatment_plan_version` matches the plan's current version (otherwise
    `ERR_STALE_PLAN_VERSION`), and when `sessions_committed` equals 0 (otherwise
    `ERR_PLAN_HAS_COMMITTED_SESSIONS`)."

    Design: Corner/errors/cancel_plan_with_committed_session_returns_has_committed
    """
    sc = setup_committed_session(member=False, list_price_per_unit_cents=1000,
                                 planned_units=20, max_units_authorized=30)
    admin = make_clinic_admin_headers()
    pv = plan_version(sc.plan_id, sc.injector_id)
    resp = api.cancel_plan(sc.plan_id, {"expected_treatment_plan_version": pv}, admin)
    validate_error(resp, ApiErrorId.ERR_PLAN_HAS_COMMITTED_SESSIONS.value)
