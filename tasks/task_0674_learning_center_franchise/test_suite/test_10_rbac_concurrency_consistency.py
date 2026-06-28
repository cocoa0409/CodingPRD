"""RBAC denials, optimistic-concurrency rejections, derived-field reconciliation,
and immediate-consistency corners.

Queue B — Corner/rbac, Corner/cross_cutting_complexity_layers, Corner/consistency_model.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, build_user_headers,
    setup_operating_center_with_subject, setup_active_enrollment,
    setup_active_enrollment_with_worksheet,
    create_family, create_student, create_and_place_enrollment,
    create_and_open_session, family_version, create_invoice,
    make_franchise_admin_headers, make_center_director_headers,
    make_instructor_headers, make_parent_headers,
)
from test_helpers import api_client as api

ADMIN = make_franchise_admin_headers()
DIRECTOR = make_center_director_headers()
INSTRUCTOR = make_instructor_headers()


# ------------------------------- rbac ------------------------------------
def test_instructor_cannot_create_center():
    """PRD §2.1: "When the headers are present and valid but the role is not permitted
    to perform the requested operation ... the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §4 (endpoint table): "POST | `/centers` | Create a center | FranchiseAdmin"

    Design: Corner/rbac/instructor_cannot_create_center
    """
    headers = build_user_headers("instr-9", "Instructor")
    resp = api.create_center({"name": "Sneaky", "territory_code": "TER-FB"}, headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_parent_cannot_grade_worksheet():
    """PRD §2.1: "When the headers are present and valid but the role is not permitted to
    perform the requested operation ... the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §4 (endpoint table): "POST | `/worksheets/{worksheet_id}/grade` | Grade a
    worksheet set | Instructor"

    Grading is Instructor-exclusive; a Parent (acting as their own family) -> ERR_FORBIDDEN;
    worksheet unchanged.

    Design: Corner/rbac/parent_cannot_grade_worksheet
    """
    _c, _s, _l, family, _st, _en, ws = setup_active_enrollment_with_worksheet()
    parent = make_parent_headers(family["id"])
    resp = api.grade_worksheet(ws["id"], {"score": 90}, parent)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    fresh = validate_success(api.get_worksheet(ws["id"], DIRECTOR))
    assert fresh["status"] == "ASSIGNED"


def test_missing_headers_returns_unauthenticated():
    """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` that is
    not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api.list_centers({})  # no auth headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------- cross_cutting_complexity_layers ------------------------
def test_occ_attendance_stale_session_version_rejected():
    """PRD §2.7: "Booking a seat requires the request to carry `expected_session_version`,
    holding the client's last-observed `version` of the target `Session`. A booking is
    rejected when `expected_session_version` no longer matches the session's current
    `version`: another writer has already booked a seat (advancing the session's
    `version` and its `booked_seat_count`), so the present writer's view of remaining
    capacity is stale. This rejection also carries `ERR_STALE_VERSION` (HTTP 412)."

    A version observed before the first booking is stale for the second booking ->
    ERR_STALE_VERSION; only one seat booked.

    Design: Corner/cross_cutting_complexity_layers/occ_attendance_stale_session_version_rejected
    """
    center, subject, _level, family, _student, en1 = setup_active_enrollment(
        clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    st2 = create_student(family["id"], full_name="K2", birthdate="2017-01-01T00:00:00Z")
    en2 = create_and_place_enrollment(center["id"], st2["id"], subject["id"])
    session = create_and_open_session(center["id"], "2026-05-01T09:00:00Z",
                                      "2026-05-01T10:00:00Z", 3)
    observed_version = session["version"]
    # First booking succeeds and advances Session.version.
    validate_success(api.create_attendance_record(
        {"session_id": session["id"], "enrollment_id": en1["id"],
         "expected_session_version": observed_version}, DIRECTOR), expected_status=201)
    # Second booking still carries the stale pre-booking version.
    resp = api.create_attendance_record(
        {"session_id": session["id"], "enrollment_id": en2["id"],
         "expected_session_version": observed_version}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    fresh = validate_success(api.get_session(session["id"], DIRECTOR))
    assert fresh["booked_seat_count"] == 1


def test_occ_invoice_stale_family_version_rejected():
    """PRD §2.7: "Creating a draft invoice for a family requires the request to carry
    `expected_family_version`, holding the client's last-observed `version` of the target
    `Family`. Drafting an invoice bills tuition and enrollment fees that supersede the
    family's prior unbilled state, so the create is rejected when `expected_family_version`
    no longer matches the family's current `version` ... The rejection carries
    `ERR_STALE_VERSION` (HTTP 412)."

    A version observed before the first invoice create is stale for the second create ->
    ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_invoice_stale_family_version_rejected
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(
        num_levels=1, monthly_tuition_cents=15000, enrollment_fee_cents=5000)
    family = create_family(center["id"])
    student = create_student(family["id"])
    create_and_place_enrollment(center["id"], student["id"], subject["id"])
    observed = family_version(family["id"])
    validate_success(api.create_invoice(
        {"family_id": family["id"], "center_id": center["id"], "period_month": "2026-05",
         "expected_family_version": observed}, DIRECTOR), expected_status=201)
    resp = api.create_invoice(
        {"family_id": family["id"], "center_id": center["id"], "period_month": "2026-06",
         "expected_family_version": observed}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_enrollment_fee_charged_once_derived_field_reconciliation():
    """PRD §3.3: "A new student carries `enrollment_fee_charged` set to false; this flag
    flips to true the first time the one-time enrollment fee has been billed for that
    student, and once true it is never charged again."
    PRD §3.7: "the `enrollment_fee_component_cents` is the sum, over the students newly
    charged on this invoice, of the center's `enrollment_fee_cents` (each student charged
    the one-time fee at most once, ever)"

    After a first invoice charges the fee, a second invoice the next period carries tuition
    but enrollment_fee_component_cents 0.

    Design: Corner/cross_cutting_complexity_layers/enrollment_fee_charged_once_derived_field_reconciliation
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(
        num_levels=1, monthly_tuition_cents=15000, enrollment_fee_cents=5000)
    family = create_family(center["id"])
    student = create_student(family["id"])
    create_and_place_enrollment(center["id"], student["id"], subject["id"])
    inv1 = create_invoice(family["id"], center["id"], "2026-05")
    validate_success(api.issue_invoice(inv1["id"], DIRECTOR))
    validate_success(api.pay_invoice(inv1["id"], {"amount_cents": 20000}, DIRECTOR))

    inv2 = create_invoice(family["id"], center["id"], "2026-06")
    fresh2 = validate_success(api.get_invoice(inv2["id"], DIRECTOR))
    assert fresh2["enrollment_fee_component_cents"] == 0, "fee already charged once"
    assert fresh2["tuition_component_cents"] == 15000


# ---------------------------- consistency_model --------------------------
def test_place_response_reflects_all_cascades_immediately():
    """PRD §2.5: "when a child event changes the basis for a derived parent value, the
    server recomputes that value immediately."
    PRD §3.6: "a `sibling_count` of exactly two earns a 5 percent discount"

    After placing the second sibling, an immediate GET of the first enrollment reflects
    the re-derived 14250 and the family's sibling_count 2 within the same request lifecycle.

    Design: Corner/consistency_model/place_response_reflects_all_cascades_immediately
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(num_levels=1)
    family = create_family(center["id"])
    st1 = create_student(family["id"], full_name="S1")
    st2 = create_student(family["id"], full_name="S2", birthdate="2017-01-01T00:00:00Z")
    en1 = create_and_place_enrollment(center["id"], st1["id"], subject["id"])
    create_and_place_enrollment(center["id"], st2["id"], subject["id"])

    fresh1 = validate_success(api.get_enrollment(en1["id"], DIRECTOR))
    fam = validate_success(api.get_family(family["id"], DIRECTOR))
    assert fresh1["monthly_rate_cents"] == 14250
    assert fam["sibling_count"] == 2
