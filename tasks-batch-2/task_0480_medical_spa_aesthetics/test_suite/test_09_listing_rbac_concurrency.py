"""Listing/pagination, RBAC, and cross-cutting complexity-layer tests
(§2.1, §2.3, §2.9, §3.1, §3.4, §3.5).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    make_provider_headers,
    make_clinic_admin_headers,
    make_injector,
    make_director,
    make_patient,
    make_lot,
    sign_consent,
    make_consultation,
    complete_exam,
    make_standing_order,
    make_plan,
    activate_plan,
    book_session,
    setup_active_plan,
    setup_proposed_plan,
    plan_version,
    post_deposit,
    create_provider_payload,
    create_injectable_lot_payload,
    create_treatment_session_payload,
    create_deposit_payload,
    create_consent_photo_payload,
)

ADMIN = make_clinic_admin_headers()


# ---------------------------------------------------------------------------
# endpoints: pagination + filtered reverse-FK
# ---------------------------------------------------------------------------
def test_list_providers_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope." PRD §2.3: "The `limit`
    parameter caps how many items are returned; it defaults to 10, may not be
    smaller than 1, and may not exceed 100."

    With two providers and limit=1, total_count==2 and has_more==true.

    Design: Corner/endpoints/list_providers_pagination_envelope
    """
    make_injector(license_number="L-PG-1")
    make_director(license_number="L-PG-2")
    data, meta = validate_paginated(api.list_providers(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"total_count should be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more should be true, got {meta['has_more']}"
    assert len(data) == 1, f"limit=1 should return 1 item, got {len(data)}"


def test_filtered_list_sessions_by_plan(api):
    """PRD §3.4: "Sessions may be listed with optional `treatment_plan_id`,
    `standing_order_id`, `injector_provider_id`, `injectable_lot_id`, and `status`
    filters."

    GET /aesthetics/treatment-sessions?treatment_plan_id={id} returns exactly the
    sessions for that plan.

    Design: Corner/endpoints/filtered_list_sessions_by_plan_reverse_fk
    """
    inj = make_injector(license_number="L-FL-I")["id"]
    director = make_director(license_number="L-FL-D")["id"]
    lot = make_lot(product="BOTOX", lot_number="LOT-FL")["id"]
    patient = make_patient(full_name="Fl Pat")["id"]
    sign_consent(patient, inj)
    cons = make_consultation(patient, inj)["id"]
    complete_exam(cons, inj)
    order = make_standing_order(cons, director, product="BOTOX",
                                max_units_authorized=30)["id"]
    plan = make_plan(patient, cons, inj, product="BOTOX", planned_units_per_session=20)
    activated = activate_plan(plan["id"], plan["version"], inj)
    book_session(plan["id"], order, inj, lot, 20, activated["version"])

    data, meta = validate_paginated(api.list_treatment_sessions(
        make_provider_headers(inj), params={"treatment_plan_id": plan["id"]}))
    assert meta["total_count"] == 1, f"total_count should be 1, got {meta['total_count']}"
    assert all(s["treatment_plan_id"] == plan["id"] for s in data), (
        "filtered list must contain only the plan's sessions")


# ---------------------------------------------------------------------------
# rbac
# ---------------------------------------------------------------------------
def test_clinicadmin_cannot_book_session(api):
    """PRD §2.1: "A `ClinicAdmin` may never perform a clinical injection or sign an
    order." PRD §2.1: "When the headers are present and valid but the role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Booking is a `Provider`-exclusive clinical op; a `ClinicAdmin` caller is rejected.

    Design: Corner/rbac/clinicadmin_cannot_book_session_returns_forbidden
    """
    sc = setup_active_plan()
    payload = create_treatment_session_payload(
        sc.plan_id, sc.standing_order_id, sc.injector_id, sc.lot_id, 20, sc.plan_version)
    resp = api.create_treatment_session(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_provider_cannot_intake_lot(api):
    """PRD §2.1: "The `ClinicAdmin` role owns front-office and operational concerns:
    registering and suspending providers, creating membership packages, intaking
    and quarantining injectable lots, ..." PRD §2.1: "When the headers are present
    and valid but the role is not permitted to perform the requested operation,
    the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Lot intake is `ClinicAdmin`-exclusive; a `Provider` caller is rejected.

    Design: Corner/rbac/provider_cannot_intake_lot_returns_forbidden
    """
    inj = make_injector(license_number="L-RB2-I")["id"]
    resp = api.create_injectable_lot(
        create_injectable_lot_payload(product="BOTOX", lot_number="LOT-RB2"),
        make_provider_headers(inj))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers
# ---------------------------------------------------------------------------
def test_occ_stale_plan_version_on_deposit(api):
    """PRD §2.9: "Plan activation, completion, and cancellation, posting a
    deposit, and booking a treatment session each require
    `expected_treatment_plan_version` to equal the target `TreatmentPlan`'s current
    version, failing with `ERR_STALE_PLAN_VERSION`." PRD §3.3: "posting it adds its
    `amount_cents` to the plan's `deposit_paid_cents` and increments the plan's
    version by 1."

    Posting a second deposit with the now-stale version (the first deposit
    advanced plan.version) is rejected `ERR_STALE_PLAN_VERSION` (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_on_deposit_returns_412
    """
    sc = setup_proposed_plan(required_deposit_cents=10000, sign_order=False)
    stale_v = sc.plan_version
    post_deposit(sc.plan_id, 5000, stale_v)  # advances version
    resp = api.create_deposit(
        create_deposit_payload(sc.plan_id, 5000, stale_v), ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_PLAN_VERSION.value)


def test_photo_consent_on_file_reconciles_after_signed_consent(api):
    """PRD §3.1: "Each patient carries the computed flag `photo_consent_on_file`,
    which begins `false` and becomes `true` once a signed consent record exists for
    that patient (see §3.5)." PRD §3.5: "A `CONSENT` record with signed set to `true`
    represents a signed consent; recording such a record flips the subject
    patient's `photo_consent_on_file` to `true`."

    Design: Corner/cross_cutting_complexity_layers/derived_photo_consent_on_file_reconciles_after_signed_consent
    """
    inj = make_injector(license_number="L-DR-I")["id"]
    patient = make_patient(full_name="Dr Pat")
    assert patient["photo_consent_on_file"] is False
    validate_success(api.create_consent_photo(
        create_consent_photo_payload(patient["id"], kind="CONSENT",
                                     storage_uri="s3://dr-c", signed=True),
        make_provider_headers(inj)), expected_status=201)
    refreshed = validate_success(api.get_patient(patient["id"], make_provider_headers(inj)))
    assert refreshed["photo_consent_on_file"] is True, (
        "photo_consent_on_file should flip to true after a signed CONSENT record")


def test_quarantined_lot_excluded_from_fefo(api):
    """PRD §3.1: "Quarantining a lot sets `status` to `QUARANTINED`; a `QUARANTINED` lot
    can no longer back new reservations." PRD §3.4: "the sum of `remaining_units`
    across all `AVAILABLE`, non-expired lots of the plan's product must be at least
    `planned_units` (otherwise `ERR_INSUFFICIENT_LOT_UNITS`)."

    After quarantining the only lot, booking finds no `AVAILABLE` units and is
    rejected `ERR_INSUFFICIENT_LOT_UNITS`.

    Design: Corner/cross_cutting_complexity_layers/cascade_quarantine_lot_excluded_from_fefo
    """
    inj = make_injector(license_number="L-QZ-I")["id"]
    director = make_director(license_number="L-QZ-D")["id"]
    lot = make_lot(product="BOTOX", lot_number="LOT-QZ")
    quar = validate_success(api.quarantine_lot(
        lot["id"], {"expected_lot_version": lot["version"]}, ADMIN))
    assert quar["status"] == "QUARANTINED"
    patient = make_patient(full_name="Qz Pat")["id"]
    sign_consent(patient, inj)
    cons = make_consultation(patient, inj)["id"]
    complete_exam(cons, inj)
    order = make_standing_order(cons, director, product="BOTOX",
                                max_units_authorized=30)["id"]
    plan = make_plan(patient, cons, inj, product="BOTOX", planned_units_per_session=20)
    activated = activate_plan(plan["id"], plan["version"], inj)
    payload = create_treatment_session_payload(
        plan["id"], order, inj, lot["id"], 20, activated["version"])
    resp = api.create_treatment_session(payload, make_provider_headers(inj))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_UNITS.value)
