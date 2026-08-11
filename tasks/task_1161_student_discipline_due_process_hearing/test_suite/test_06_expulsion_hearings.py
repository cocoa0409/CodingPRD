"""Expulsion hearings: referral gate, scheduling window, officer calendar,
evidence packet, and the divergent decision cascades."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_expulsion_hearing, assert_evidence_item,
    create_hearing_payload, create_evidence_payload,
    create_evidence_ruling_payload, create_hearing_decision_payload,
    set_clock, create_offense_code, create_student, create_case,
    create_classified_case, refer_expulsion,
    setup_expulsion_referred_case, create_hearing,
    create_hearing_with_admitted_evidence, submit_evidence, rule_evidence,
    serve_packet, convene_hearing, decide_hearing, setup_hearing_held,
    get_case,
    make_school_admin_headers, make_hearing_officer_headers,
    make_district_admin_headers,
    TEST_USERS, ApiErrorId,
)

ADMIN = TEST_USERS["district_admin_headers"]
CLS = TEST_USERS["school_classifier_headers"]


def test_refer_expulsion_non_expellable_returns_409(api):
    """PRD §3.5: "Referral is lawful only when the offense code's `expellable`
    flag is true; for a non-expellable offense it is rejected with
    `ERR_OFFENSE_NOT_EXPELLABLE`."

    Design: Corner/validations/refer_expulsion_non_expellable_returns_409
    """
    set_clock("2026-05-04T00:00:00Z")
    oc = create_offense_code(expellable=False)
    student = create_student(full_name="Stu NoExp", guardian_id="gne")
    case = create_classified_case(student["id"], oc["id"],
                                  "2026-05-04T08:00:00Z")
    res = api.refer_expulsion(case["id"], {}, CLS)
    validate_error(res, ApiErrorId.ERR_OFFENSE_NOT_EXPELLABLE, expected_status=409)

    settled = get_case(case["id"])
    assert settled["status"] == "CLASSIFIED"


def test_hearing_start_beyond_ten_day_window_returns_409(api):
    """PRD §3.5: "The start must fall no later than ten days after
    `referred_to_expulsion_at`, or scheduling is rejected with
    `ERR_HEARING_WINDOW_PASSED`."

    Design: Corner/validations/hearing_start_beyond_ten_day_window_returns_409
    """
    bundle = setup_expulsion_referred_case(
        guardian_id="ghw", full_name="Stu HW")  # referred at 2026-05-04T00:00Z
    res = api.create_hearing(
        create_hearing_payload(bundle["case"]["id"], "ho_1",
                               "2026-05-15T10:00:00Z", "2026-05-15T11:00:00Z"),
        make_district_admin_headers("da_1"))
    validate_error(res, ApiErrorId.ERR_HEARING_WINDOW_PASSED, expected_status=409)


def test_hearing_second_open_for_same_case_returns_409(api):
    """PRD §3.5: "A case may carry only one open hearing — one in `SCHEDULED`,
    `EVIDENCE_SERVED`, or `HELD` status — so a second hearing for the same case
    draws `ERR_HEARING_ALREADY_OPEN`."

    Design: Corner/validations/hearing_second_open_for_same_case_returns_409
    """
    bundle = setup_expulsion_referred_case(
        guardian_id="ghao", full_name="Stu HAO")
    create_hearing(bundle["case"]["id"], "ho_1",
                   "2026-05-08T10:00:00Z", "2026-05-08T11:00:00Z")
    # Times chosen non-overlapping so only the one-open-hearing rule can fire.
    res = api.create_hearing(
        create_hearing_payload(bundle["case"]["id"], "ho_1",
                               "2026-05-08T12:00:00Z", "2026-05-08T13:00:00Z"),
        make_district_admin_headers("da_1"))
    validate_error(res, ApiErrorId.ERR_HEARING_ALREADY_OPEN, expected_status=409)


def test_hearing_officer_overlap_returns_409(api):
    """PRD §3.5: "the new hearing conflicts with any of the officer's existing
    hearings whose interval interleaves with it, which under the half-open
    convention means the new start falls before the existing hearing's end and
    the existing start falls before the new end ... A conflicting assignment
    is rejected with `ERR_HEARING_OVERLAP`."

    Design: Corner/validations/hearing_officer_overlap_returns_409
    """
    case_a = setup_expulsion_referred_case(
        guardian_id="goa", full_name="Stu OA")["case"]
    case_b = setup_expulsion_referred_case(
        guardian_id="gob", full_name="Stu OB", demographic_group="BLACK",
        incident_date="2026-05-02T00:00:00Z", clock="2026-05-04T00:00:00Z",
        offense_code="WEAP-02")["case"]
    create_hearing(case_a["id"], "ho_9",
                   "2026-05-08T10:00:00Z", "2026-05-08T12:00:00Z")
    # [10:30, 11:30) interleaves [10:00, 12:00): 10:30 < 12:00 and 10:00 < 11:30.
    res = api.create_hearing(
        create_hearing_payload(case_b["id"], "ho_9",
                               "2026-05-08T10:30:00Z", "2026-05-08T11:30:00Z"),
        make_district_admin_headers("da_1"))
    validate_error(res, ApiErrorId.ERR_HEARING_OVERLAP, expected_status=409)


def test_evidence_locked_after_packet_served_returns_409(api):
    """PRD §3.5: "Service stamps `packet_served_at` at the clock, moves the
    hearing `SCHEDULED` → `EVIDENCE_SERVED`, and forecloses any further
    evidence creation for that hearing."
    PRD §2.9: "state-guarded child creation is honored: evidence only while
    its hearing is `SCHEDULED` ... Violations are rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/evidence_locked_after_packet_served_returns_409
    """
    bundle = setup_expulsion_referred_case(
        guardian_id="gl1", full_name="Stu Lock")
    ev_bundle = create_hearing_with_admitted_evidence(
        bundle["case"]["id"], "ho_1",
        "2026-05-08T10:00:00Z", "2026-05-08T12:00:00Z")
    hearing = serve_packet(ev_bundle["hearing"]["id"])  # clock is 2026-05-04
    assert hearing["status"] == "EVIDENCE_SERVED"

    res = api.submit_evidence(
        hearing["id"], create_evidence_payload("OTHER", "late evidence"), CLS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_evidence_served_after_deadline_returns_409(api):
    """PRD §3.5: "An administrator serves the packet once at least one item
    stands `ADMITTED` — an empty packet is rejected with
    `ERR_EVIDENCE_PACKET_EMPTY` — and no later than two days before the
    scheduled start, a later service drawing `ERR_EVIDENCE_DEADLINE_PASSED`."

    Design: Corner/validations/evidence_served_after_deadline_returns_409
    """
    bundle = setup_expulsion_referred_case(
        guardian_id="gevd", full_name="Stu EvD")
    ev_bundle = create_hearing_with_admitted_evidence(
        bundle["case"]["id"], "ho_1",
        "2026-05-08T10:00:00Z", "2026-05-08T12:00:00Z")
    # One day before the start — inside the two-day lead (deadline was
    # 2026-05-06T10:00:00Z).
    set_clock("2026-05-07T10:00:00Z")
    res = api.serve_packet(ev_bundle["hearing"]["id"], {}, CLS)
    validate_error(res, ApiErrorId.ERR_EVIDENCE_DEADLINE_PASSED,
                   expected_status=409)


def test_evidence_packet_empty_returns_409(api):
    """PRD §3.5: "An administrator serves the packet once at least one item
    stands `ADMITTED` — an empty packet is rejected with
    `ERR_EVIDENCE_PACKET_EMPTY`".

    Design: Corner/validations/evidence_packet_empty_returns_409
    """
    bundle = setup_expulsion_referred_case(
        guardian_id="geve", full_name="Stu EvE")
    hearing = create_hearing(bundle["case"]["id"], "ho_1",
                             "2026-05-08T10:00:00Z", "2026-05-08T12:00:00Z")
    evidence = submit_evidence(hearing["id"], "VIDEO", "blurry clip")
    excluded = rule_evidence(evidence["id"], "EXCLUDED", "ho_1")
    assert excluded["status"] == "EXCLUDED"

    # Zero ADMITTED items; clock 2026-05-04 is within the service lead time.
    res = api.serve_packet(hearing["id"], {}, CLS)
    validate_error(res, ApiErrorId.ERR_EVIDENCE_PACKET_EMPTY, expected_status=409)


def test_not_expelled_decision_reverts_case_to_classified(api):
    """PRD §3.5: "A finding of `NOT_EXPELLED` instead reverts the case
    `EXPULSION_REFERRED` → `CLASSIFIED`, clears `referred_to_expulsion_at`
    back to empty, and lets the case resume the ordinary discipline track."

    Design: Corner/state_machines/not_expelled_decision_reverts_case_to_classified
    """
    bundle = setup_expulsion_referred_case(
        guardian_id="gn1", full_name="Stu NotExp", demographic_group="BLACK")
    held = setup_hearing_held(bundle["case"]["id"], "ho_1",
                              "2026-05-08T10:00:00Z", "2026-05-08T12:00:00Z",
                              item_type="WITNESS_STATEMENT", description="witness")
    assert held["hearing"]["status"] == "HELD"

    decided = validate_success(api.decide_hearing(
        held["hearing"]["id"],
        create_hearing_decision_payload("NOT_EXPELLED", "insufficient evidence"),
        make_hearing_officer_headers("ho_1")), 200)
    assert decided["status"] == "NOT_EXPELLED"

    case = get_case(bundle["case"]["id"])
    assert case["status"] == "CLASSIFIED", (
        f"the revert cycle edge must fire, got {case['status']!r}")
    assert case.get("referred_to_expulsion_at") is None

    student = validate_success(api.get_student(bundle["student"]["id"], CLS), 200)
    assert student["enrollment_status"] == "ENROLLED", (
        "no enrollment cascade fires on the NOT_EXPELLED branch")


# ─── Difficulty: half-open officer calendar ───────────

def _setup_two_referred_cases_shared_officer(api):
    """Two students, each with a case in EXPULSION_REFERRED (both referred at
    2026-05-04T00:00:00Z, inside the ten-day scheduling window)."""
    case_h1 = setup_expulsion_referred_case(
        guardian_id="gh1", full_name="Stu H1", date_of_birth="2008-04-01T00:00:00Z"
    )["case"]
    case_h2 = setup_expulsion_referred_case(
        guardian_id="gh2", full_name="Stu H2", date_of_birth="2008-05-01T00:00:00Z",
        demographic_group="BLACK", incident_date="2026-05-02T00:00:00Z",
        offense_code="WEAP-02")["case"]
    return case_h1, case_h2


def test_officer_adjacent_hearings_both_accepted(api):
    """PRD §3.5: "the hearing occupies the half-open interval that includes
    its start and excludes its end" and "two hearings that merely touch at an
    endpoint, one ending exactly when the other begins, do not conflict."

    Design: Difficulty/resource_temporal_overlap/hearing_officer_half_open_adjacency_allowed
    """
    case_h1, case_h2 = _setup_two_referred_cases_shared_officer(api)

    first = validate_success(api.create_hearing(
        create_hearing_payload(case_h1["id"], "ho_9",
                               "2026-05-08T10:00:00Z", "2026-05-08T12:00:00Z"),
        make_district_admin_headers("da_1")), 201)
    assert_expulsion_hearing(first)

    # Adjacency, not overlap: the second start equals the first end.
    second = validate_success(api.create_hearing(
        create_hearing_payload(case_h2["id"], "ho_9",
                               "2026-05-08T12:00:00Z", "2026-05-08T13:00:00Z"),
        make_district_admin_headers("da_1")), 201)
    assert_expulsion_hearing(second)
    assert second["scheduled_start"] == first["scheduled_end"]


def test_officer_adjacent_hearings_listed_as_two_open(api):
    """PRD §3.5: "A new hearing begins `SCHEDULED`, and the hearing register
    supports reverse-lookup filters on `case_id`, `hearing_officer_id`, and
    `status`."
    PRD §3.5: "two hearings that merely touch at an endpoint, one ending
    exactly when the other begins, do not conflict."

    Design: Difficulty/resource_temporal_overlap/hearing_officer_half_open_adjacency_allowed
    """
    case_h1, case_h2 = _setup_two_referred_cases_shared_officer(api)
    validate_success(api.create_hearing(
        create_hearing_payload(case_h1["id"], "ho_9",
                               "2026-05-08T10:00:00Z", "2026-05-08T12:00:00Z"),
        make_district_admin_headers("da_1")), 201)
    validate_success(api.create_hearing(
        create_hearing_payload(case_h2["id"], "ho_9",
                               "2026-05-08T12:00:00Z", "2026-05-08T13:00:00Z"),
        make_district_admin_headers("da_1")), 201)

    data, meta = validate_paginated(
        api.list_hearings(ADMIN, params={"hearing_officer_id": "ho_9"}))
    assert len(data) == 2 and meta["total_count"] == 2
    assert all(row["status"] == "SCHEDULED" for row in data)
    assert all(row["hearing_officer_id"] == "ho_9" for row in data)


# ─── Difficulty: expulsion cascade (hearing -> case -> student) ──

def _setup_held_hearing(api):
    """Expulsion-referred case with a HELD hearing (officer ho_1, evidence
    admitted, packet served at 2026-05-04, convened at 2026-05-08T12:00Z)."""
    bundle = setup_expulsion_referred_case(guardian_id="g4", full_name="Stu Exp",
                                           date_of_birth="2008-08-01T00:00:00Z",
                                           demographic_group="HISPANIC")
    held = setup_hearing_held(bundle["case"]["id"], "ho_1",
                              "2026-05-08T10:00:00Z", "2026-05-08T12:00:00Z")
    bundle["hearing"] = held["hearing"]
    return bundle


def test_expulsion_ordered_moves_case_to_expulsion_active(api):
    """PRD §3.5: "Ordering expulsion fires two links: the case moves
    `EXPULSION_REFERRED` → `EXPULSION_ACTIVE`, and the student's
    `enrollment_status` moves `ENROLLED` → `ALT_ED_PENDING` in the same
    motion."

    Design: Difficulty/transitive_cascade/expulsion_ordered_cascade_case_student_enrollment
    """
    bundle = _setup_held_hearing(api)
    decided = validate_success(api.decide_hearing(
        bundle["hearing"]["id"],
        create_hearing_decision_payload("EXPULSION_ORDERED",
                                        "preponderance of evidence"),
        make_hearing_officer_headers("ho_1")), 200)
    assert decided["status"] == "EXPULSION_ORDERED", "trigger: hearing decided"

    case = get_case(bundle["case"]["id"])
    assert case["status"] == "EXPULSION_ACTIVE", (
        f"link 1 (hearing decision -> case): got {case['status']!r}")


def test_expulsion_ordered_flips_student_to_alt_ed_pending(api):
    """PRD §3.5: "Ordering expulsion fires two links: the case moves
    `EXPULSION_REFERRED` → `EXPULSION_ACTIVE`, and the student's
    `enrollment_status` moves `ENROLLED` → `ALT_ED_PENDING` in the same
    motion."

    Design: Difficulty/transitive_cascade/expulsion_ordered_cascade_case_student_enrollment
    """
    bundle = _setup_held_hearing(api)
    validate_success(api.decide_hearing(
        bundle["hearing"]["id"],
        create_hearing_decision_payload("EXPULSION_ORDERED"),
        make_hearing_officer_headers("ho_1")), 200)

    student = validate_success(
        api.get_student(bundle["student"]["id"], CLS), 200)
    assert student["enrollment_status"] == "ALT_ED_PENDING", (
        "link 2 (case mutation -> student): enrollment_status must be "
        f"ALT_ED_PENDING, got {student['enrollment_status']!r}")
