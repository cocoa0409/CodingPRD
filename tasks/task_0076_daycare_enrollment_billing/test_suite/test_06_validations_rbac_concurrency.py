"""Validation ordering / priority conflicts, RBAC, ownership, optimistic
concurrency on enrollment creation, and request-shape validation.

Translates queue-A difficulty instances (priority_pair_validation_conflict) and
queue-B corner instances (validations, rbac, errors-as-positive-trigger via
cross_cutting OCC, auth).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_director_headers, make_billing_headers, make_parent_headers,
    build_user_headers, NON_EXISTENT_UUID, ApiErrorId,
)
import test_helpers.fixtures as fx

DIRECTOR = make_director_headers()
BILLING = make_billing_headers()


def test_void_paid_invoice_state_beats_fiscal(api):
    """PRD §2.6: "Only then are state-machine preconditions evaluated: an operation
    whose transition is not defined from the resource's current state fails with
    ERR_INVALID_STATE. Business rules specific to each workflow (offer expiry,
    age-band fit, duplicate guards, capacity, fiscal rules, and so on) follow".

    Voiding a PAID invoice: state (void undefined from PAID) outranks the
    has-payments fiscal rule -> ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_void_paid_invoice
    """
    center, classroom, family, child, enrollment, paid = fx.setup_paid_invoice(
        base_tuition_cents=120000)
    assert paid["status"] == "PAID"
    resp = api.void_invoice(paid["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_void_paid_invoice_not_reported_as_has_payments(api):
    """PRD §2.6: "an operation whose transition is not defined from the resource's
    current state fails with ERR_INVALID_STATE. Business rules specific to each
    workflow (offer expiry, age-band fit, duplicate guards, capacity, fiscal rules,
    and so on) follow".

    The lower-priority fiscal error (ERR_INVOICE_HAS_PAYMENTS) must NOT pre-empt the
    state check on a PAID invoice.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_void_paid_invoice
    """
    center, classroom, family, child, enrollment, paid = fx.setup_paid_invoice(
        base_tuition_cents=120000)
    resp = api.void_invoice(paid["id"], BILLING)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] != ApiErrorId.ERR_INVOICE_HAS_PAYMENTS.value


def test_activate_missing_enrollment_existence_beats_capacity(api):
    """PRD §2.6: "Existence of every path-referenced resource is third
    (ERR_NOT_FOUND) ... Business rules specific to each workflow (offer expiry,
    age-band fit, duplicate guards, capacity, fiscal rules, and so on) follow".

    Activating a non-existent enrollment id: existence (ERR_NOT_FOUND) outranks the
    capacity gate even though a full classroom exists.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_safety_activate_missing_enrollment
    """
    # A full capacity-1 classroom exists, but the target enrollment id is bogus.
    fx.setup_single_active_enrollment(classroom_overrides={"licensed_capacity": 1})
    resp = api.activate_enrollment(NON_EXISTENT_UUID, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_activate_missing_enrollment_not_reported_as_classroom_full(api):
    """PRD §2.6: "a missing resource is reported before any state or business rule
    is consulted."

    Even with a FULL classroom present, a non-existent enrollment must surface
    ERR_NOT_FOUND, never ERR_CLASSROOM_FULL.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_safety_activate_missing_enrollment
    """
    fx.setup_single_active_enrollment(classroom_overrides={"licensed_capacity": 1})
    resp = api.activate_enrollment(NON_EXISTENT_UUID, DIRECTOR)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
    assert err["error_id"] != ApiErrorId.ERR_CLASSROOM_FULL.value


def test_age_band_mismatch_on_activate_rejected(api):
    """PRD §3.4: "The child's birthdate must also fit the classroom's age_band
    bounds; a mismatch is rejected with ERR_AGE_BAND_MISMATCH."

    Design: Corner/validations/age_band_mismatch_on_activate_rejected
    """
    fx.set_clock("2026-03-02T08:00:00Z")
    center = fx.create_center(cacfp_tier="TIER_I")
    fx.add_full_pay_scale(center["id"])
    classroom = fx.create_classroom(
        center["id"], name="Inf", age_band="INFANT", licensed_capacity=5,
        base_monthly_tuition_cents=150000)
    family = fx.create_family(center["id"])
    child = fx.create_child(family["id"], full_name="Big", birthdate="2018-01-10")
    _, enrollment = fx.create_offered_enrollment(classroom, family, child=child)
    fx.accept_enrollment(enrollment, family)
    resp = api.activate_enrollment(enrollment["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_AGE_BAND_MISMATCH.value)


def test_duplicate_enrollment_rejected(api):
    """PRD §3.4: "A child may not hold two non-terminal enrollments at once — that
    is, two in any of OFFERED, ACCEPTED, or ACTIVE — and an attempt to create a
    second is rejected with ERR_DUPLICATE_ENROLLMENT."

    Design: Corner/validations/duplicate_enrollment_rejected
    """
    center, classroom, family = fx.setup_center_classroom_family()
    child, enrollment = fx.create_offered_enrollment(classroom, family)
    room = get_success_data(api.get_classroom(classroom["id"], DIRECTOR))
    resp = api.create_enrollment(
        {"child_id": child["id"], "classroom_id": classroom["id"],
         "expected_classroom_version": room["version"]}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value)


def test_reference_not_found_on_enrollment_bad_child(api):
    """PRD §2.5: "When a creation payload references another resource — for example
    a classroom_id, child_id, family_id, invoice_id, or waitlist_entry_id — and
    that reference does not resolve to an existing resource, the request is rejected
    with ERR_REFERENCE_NOT_FOUND."

    Design: Corner/validations/reference_not_found_on_enrollment_bad_child
    """
    center = fx.create_center(cacfp_tier="TIER_I")
    classroom = fx.create_classroom(center["id"])
    room = get_success_data(api.get_classroom(classroom["id"], DIRECTOR))
    resp = api.create_enrollment(
        {"child_id": NON_EXISTENT_UUID, "classroom_id": classroom["id"],
         "expected_classroom_version": room["version"]}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


def test_parent_cannot_activate_enrollment_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."

    Activation is a CenterDirector operation per §4; a Parent is forbidden.

    Design: Corner/rbac/parent_cannot_activate_enrollment_forbidden
    """
    center, classroom, family = fx.setup_center_classroom_family()
    child, enrollment = fx.create_offered_enrollment(classroom, family)
    fx.accept_enrollment(enrollment, family)
    parent = make_parent_headers(family["id"])
    resp = api.activate_enrollment(enrollment["id"], parent)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_parent_cannot_accept_other_familys_enrollment(api):
    """PRD §2.1: "a parent may act on a child, a waitlist entry, or an enrollment
    only when the underlying Child belongs to that family, and a violation is
    rejected with ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/parent_cannot_accept_other_familys_enrollment_not_owner
    """
    center, classroom, family_a = fx.setup_center_classroom_family()
    family_b = fx.create_family(center["id"], primary_contact_name="B")
    child_a, enr_a = fx.create_offered_enrollment(classroom, family_a)
    wrong_parent = make_parent_headers(family_b["id"])
    resp = api.accept_enrollment(enr_a["id"], wrong_parent)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_unknown_role_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of these
    four known roles, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    bad_headers = build_user_headers("someone", "Nobody")
    resp = api.create_center({"name": "C", "cacfp_tier": "TIER_I"}, bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_occ_enrollment_create_stale_classroom_version_rejected(api):
    """PRD §2.7: "A create-enrollment request must carry expected_classroom_version,
    a non-optional field holding the client's last observed version of the target
    Classroom. If that value does not equal the classroom's current version ... the
    create is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_enrollment_create_stale_classroom_version_rejected
    """
    center = fx.create_center(cacfp_tier="TIER_I")
    classroom = fx.create_classroom(center["id"])
    family = fx.create_family(center["id"])
    v0 = classroom["version"]
    kid1 = fx.create_child(family["id"], full_name="K1")
    kid2 = fx.create_child(family["id"], full_name="K2")
    # First create advances the classroom version.
    get_success_data(api.create_enrollment(
        {"child_id": kid1["id"], "classroom_id": classroom["id"],
         "expected_classroom_version": v0}, DIRECTOR))
    resp = api.create_enrollment(
        {"child_id": kid2["id"], "classroom_id": classroom["id"],
         "expected_classroom_version": v0}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
