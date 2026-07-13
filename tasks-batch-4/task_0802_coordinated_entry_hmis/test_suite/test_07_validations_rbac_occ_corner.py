"""Breadth business-validation, RBAC, authentication, and optimistic-concurrency tests.

Every test translates exactly one non-stub instance from the corner design index (queue B).
"""
from test_helpers import (
    validate_success, validate_error,
    create_bed_payload, create_bed_reservation_payload, create_waitlist_entry_payload,
    create_prioritization_entry_payload, create_assessment_payload, create_client_payload,
    new_client, new_active_client, new_active_consent, new_consent,
    new_shelter, new_shelter_with_beds, add_bed, shelter_version,
    new_waitlist_entry, new_reservation, new_exit_record, new_referral,
    setup_accepted_referral, setup_active_pooled_client, setup_completed_shelter_stay,
    make_navigator_headers,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_headers"]
SHELTER = TEST_USERS["shelter_manager_headers"]
ADMIN = TEST_USERS["hmis_admin_headers"]


# ─── validations ──────────────────────────────────────────────────────────────
def test_duplicate_bed_label_rejected(api):
    """PRD §3.4: "the label must be unique within its shelter, and a collision is rejected
    with `ERR_DUPLICATE_BED_LABEL`."

    Design: Corner/validations/val_duplicate_bed_label_rejected
    """
    shelter = new_shelter(name="Dup ES")
    add_bed(shelter["id"], "B1")
    res = api.create_bed(create_bed_payload(shelter["id"], "B1"), SHELTER)
    validate_error(res, "ERR_DUPLICATE_BED_LABEL", expected_status=409)


def test_duplicate_waitlist_entry_rejected(api):
    """PRD §3.5: "A client may hold only one active waiting entry per shelter; a second
    `WAITING` entry at the same shelter is rejected with `ERR_DUPLICATE_WAITLIST`."

    Design: Corner/validations/val_duplicate_waitlist_rejected
    """
    client = new_client(full_name="Wait Twice", dob="1990-01-01")
    shelter, _ = new_shelter_with_beds(("B1",), name="Wait ES")
    new_waitlist_entry(shelter["id"], client["id"], "2026-03-06", "2026-03-19")
    res = api.create_waitlist_entry(create_waitlist_entry_payload(
        shelter["id"], client["id"], "2026-03-06", "2026-03-19"), SHELTER)
    validate_error(res, "ERR_DUPLICATE_WAITLIST", expected_status=409)


def test_pool_placement_without_active_consent_rejected(api):
    """PRD §3.6: "Placement requires the client to hold an `ACTIVE` `ROIConsent` and to have
    no existing non-terminal pool entry; either failing condition is rejected with
    `ERR_POOL_INELIGIBLE`."

    Design: Corner/validations/val_pool_ineligible_without_consent_rejected
    """
    client = new_client(full_name="No Consent Pool", dob="1990-01-01")
    new_consent(client["id"])  # PENDING, never activated
    res = api.create_prioritization_entry(
        create_prioritization_entry_payload(client["id"]), ADMIN)
    validate_error(res, "ERR_POOL_INELIGIBLE", expected_status=409)


def test_self_merge_rejected(api):
    """PRD §3.7: "The duplicate and master must be different clients, and the duplicate must
    not already be `MERGED`; a self-merge or an already-merged duplicate is rejected with
    `ERR_MERGE_INVALID`."

    Design: Corner/validations/val_merge_same_client_rejected
    """
    client, _ = new_active_client(self_report_points=5, full_name="Self Merge", dob="1990-01-01")
    new_active_consent(client["id"])
    res = api.merge_client(client["id"], {"duplicate_client_id": client["id"]}, ADMIN)
    validate_error(res, "ERR_MERGE_INVALID", expected_status=409)


def test_merge_duplicate_without_active_consent_rejected(api):
    """PRD §3.7: "The duplicate must also hold an `ACTIVE` `ROIConsent` — de-duplication is a
    data-sharing act and requires consent — or the merge is rejected with
    `ERR_CONSENT_REQUIRED`."

    Design: Corner/validations/val_merge_without_active_consent_rejected
    """
    master = new_client(full_name="Master NC", dob="1970-01-01")
    dup, _ = new_active_client(self_report_points=5, full_name="Dupe NC", dob="1970-01-01")
    res = api.merge_client(master["id"], {"duplicate_client_id": dup["id"]}, ADMIN)
    validate_error(res, "ERR_CONSENT_REQUIRED", expected_status=409)


def test_accept_over_caseload_full_rejected(api):
    """PRD §3.6: "A `PENDING` referral moves to `ACCEPTED` only if the navigator's
    `current_caseload` is below their `max_caseload`; otherwise the request is rejected with
    `ERR_CASELOAD_FULL`."

    Design: Corner/validations/val_caseload_full_on_accept_rejected
    """
    ctx = setup_accepted_referral(max_caseload=1)  # navigator now at caseload 1 (== max)
    nav = ctx["navigator"]
    other = setup_active_pooled_client(self_report_points=9)
    ref_b = new_referral(other["client"]["id"], other["pool_entry"]["id"], nav["id"])
    res = api.accept_referral(ref_b["id"], make_navigator_headers(nav["id"]))
    validate_error(res, "ERR_CASELOAD_FULL", expected_status=409)


def test_second_exit_record_rejected(api):
    """PRD §3.8: "The referenced enrollment must not already have been exited, or the request
    is rejected with `ERR_ALREADY_EXITED`."

    Design: Corner/validations/val_exit_already_exited_rejected
    """
    ctx = setup_completed_shelter_stay(
        entry_date="2026-03-05", start_iso="2026-03-05T00:00:00Z",
        checkout_iso="2026-03-10T00:00:00Z", expected_exit_date="2026-03-20",
        shelter_name="Once ES")
    new_exit_record(ctx["client"]["id"], "PERMANENT_HOUSING",
                    reservation_id=ctx["reservation"]["id"])
    res = api.create_exit_record(
        {"client_id": ctx["client"]["id"], "reservation_id": ctx["reservation"]["id"],
         "destination": "STREET"}, SHELTER)
    validate_error(res, "ERR_ALREADY_EXITED", expected_status=409)


# ─── RBAC + authentication ────────────────────────────────────────────────────
def test_shelter_manager_cannot_create_assessment(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/rbac_shelter_manager_cannot_create_assessment
    """
    client = new_client(full_name="Rbac Client", dob="1990-01-01")
    res = api.create_assessment(
        create_assessment_payload(client["id"], self_report_points=5), SHELTER)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_intake_specialist_cannot_create_bed(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/rbac_intake_specialist_cannot_create_bed
    """
    shelter = new_shelter(name="Rbac ES")
    res = api.create_bed(create_bed_payload(shelter["id"], "B1"), INTAKE)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_missing_user_id_header_unauthenticated(api):
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational
    capacity. If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/auth_missing_user_id_header_unauthenticated
    """
    headers = {"X-User-Role": "IntakeSpecialist", "Content-Type": "application/json"}
    res = api.create_client(create_client_payload("No Auth", "1990-01-01"), headers)
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── cross-cutting: optimistic concurrency + selector ─────────────────────────
def test_stale_shelter_version_on_reservation_rejected(api):
    """PRD §2.6: "If another writer has advanced the shelter's `version` since then — by
    booking, cancelling, checking in or out, or taking a bed offline or online, all of which
    legitimately mutate the shared pool — then the caller's view of availability is stale and
    the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_reservation_create_stale_shelter_version_rejected
    """
    ca = new_client(full_name="Occ A", dob="1990-01-01")
    cb = new_client(full_name="Occ B", dob="1990-02-02")
    shelter, _ = new_shelter_with_beds(("B1", "B2"), name="Occ ES")
    shv0 = shelter_version(shelter["id"])
    new_reservation(ca["id"], shelter["id"], "2026-03-05", "2026-03-20", shv0)  # advances version

    res = api.create_bed_reservation(create_bed_reservation_payload(
        cb["id"], shelter["id"], "2026-03-05", "2026-03-20", shv0), SHELTER)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_fresh_shelter_version_on_reservation_succeeds(api):
    """PRD §2.5: "On bed-reservation creation, the supplied `expected_shelter_version` must
    equal the shelter's current `version`, or the request fails with `ERR_STALE_VERSION`
    (412). This applies only to reservation creation."

    Design: Corner/cross_cutting/occ_reservation_create_fresh_version_succeeds
    """
    ca = new_client(full_name="Fresh V", dob="1990-01-01")
    shelter, _ = new_shelter_with_beds(("B1",), name="Fresh ES")
    shv = shelter_version(shelter["id"])
    res = api.create_bed_reservation(create_bed_reservation_payload(
        ca["id"], shelter["id"], "2026-03-05", "2026-03-20", shv), SHELTER)
    reservation = validate_success(res, 201)
    assert reservation["status"] == "RESERVED"


def test_bed_assignment_selects_earliest_created_bed(api):
    """PRD §3.4: "Among the qualifying beds it selects the one created earliest, breaking ties
    by `label` in ascending order (the resource `id` is never used as a tie-break); that bed's
    `id` becomes the reservation's `bed_id`."

    Design: Corner/cross_cutting/selector_bed_assignment_created_at_tiebreak
    """
    ca = new_client(full_name="Sel Client", dob="1990-01-01")
    shelter, beds = new_shelter_with_beds(("B1", "B2"), name="Sel ES")
    reservation = new_reservation(ca["id"], shelter["id"], "2026-03-05", "2026-03-20")
    assert reservation["bed_id"] == beds[0]["id"], "reservation must land on the earliest-created bed"
