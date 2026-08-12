"""Manifestation determination: threshold trigger, IDEA gates, the day cap,
and the completion deadline."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    assert_manifestation_determination,
    create_mdr_schedule_payload, create_mdr_complete_payload,
    create_sanction_payload,
    set_clock, create_offense_code_with_bands, create_student,
    create_classified_case, propose_sanction,
    setup_case_with_auto_mdr, setup_expulsion_referred_case,
    get_case, list_open_mdrs,
    make_student_services_headers,
    TEST_USERS, ApiErrorId,
)

CLS = TEST_USERS["school_classifier_headers"]
SSD = TEST_USERS["student_services_headers"]


# ─── Difficulty: ten-day threshold boundary ───────────

def test_mdr_threshold_exactly_ten_days_not_triggered(api):
    """PRD §3.3: "`mdr_required` is true exactly when the student's
    `disability_status` is `IEP` or `SECTION_504` and the sum of the student's
    `cumulative_suspension_days` and the proposed days is strictly greater
    than ten — a combined total of exactly ten does not trigger it."

    Design: Difficulty/boundary_precision_check/mdr_threshold_exactly_ten_days_not_triggered
    """
    # cumulative 4 (confirmed) + proposed 6 lands exactly on 10.
    bundle = setup_case_with_auto_mdr(guardian_id="g6", proposed_days=6)
    case2 = bundle["case2"]
    assert case2["mdr_required"] is False, (
        "cumulative 4 + proposed 6 == 10 and the trigger is strict > 10, so "
        f"mdr_required must be false, got {case2['mdr_required']!r}")
    # 6 > occurrence-2 band max 4, justified: the override branch stands.
    assert case2["sanction_override"] is True
    assert case2["proposed_sanction_days"] == 6


def test_mdr_threshold_exactly_ten_days_creates_no_mdr(api):
    """PRD §3.3: "When the flag comes out true and no manifestation
    determination for the case currently stands `PENDING` or `SCHEDULED`, the
    proposal automatically opens one with `origin` `AUTO_THRESHOLD`, status
    `PENDING`, and a `due_at` ten days after its creation."
    PRD §3.3: "a combined total of exactly ten does not trigger it."

    Design: Difficulty/boundary_precision_check/mdr_threshold_exactly_ten_days_not_triggered
    """
    bundle = setup_case_with_auto_mdr(guardian_id="g6", proposed_days=6)
    mdrs = validate_success(
        api.list_manifestation_determinations(bundle["case2"]["id"], SSD), 200)
    assert mdrs == [], (
        f"no MDR may be auto-created at exactly ten days, got {mdrs!r}")


# ─── Difficulty: notice gated on the child MDR ────────

def test_notice_blocked_by_pending_mdr(api):
    """PRD §3.4: "no manifestation determination for the case may stand
    `PENDING` or `SCHEDULED` (`ERR_MDR_INCOMPLETE`)".

    Design: Difficulty/cross_entity_state_dependency/notice_blocked_by_pending_mdr
    """
    # cumulative 4 + proposed 7 = 11 > 10 -> AUTO_THRESHOLD MDR opens PENDING.
    bundle = setup_case_with_auto_mdr(guardian_id="g8", proposed_days=7)

    res = api.issue_notice(bundle["case2"]["id"], {"delivery_method": "EMAIL"},
                           CLS)
    validate_error(res, ApiErrorId.ERR_MDR_INCOMPLETE, expected_status=409)

    case2 = get_case(bundle["case2"]["id"])
    assert case2["status"] == "SANCTION_PROPOSED", (
        f"the blocked transition leaves the case SANCTION_PROPOSED, got "
        f"{case2['status']!r}")


def test_pending_mdr_visible_with_auto_threshold_origin(api):
    """PRD §3.3: "the proposal automatically opens one with `origin`
    `AUTO_THRESHOLD`, status `PENDING`, and a `due_at` ten days after its
    creation."
    PRD §3.6: "A case's determinations can be listed by district and school
    staff and the director, which is also the discovery channel for an
    auto-created one."

    Design: Difficulty/cross_entity_state_dependency/notice_blocked_by_pending_mdr
    """
    bundle = setup_case_with_auto_mdr(guardian_id="g8", proposed_days=7)

    mdrs = validate_success(api.list_manifestation_determinations(
        bundle["case2"]["id"], SSD), 200)
    assert len(mdrs) == 1, f"exactly one auto-created MDR, got {len(mdrs)}"
    assert_manifestation_determination(mdrs[0])
    assert mdrs[0]["status"] == "PENDING"
    assert mdrs[0]["origin"] == "AUTO_THRESHOLD"
    assert mdrs[0]["case_id"] == bundle["case2"]["id"]


# ─── Corner: cap, deadline, manual-door rules ─────────

def test_mdr_yes_caps_proposed_sanction_to_six(api):
    """PRD §3.6: "When the outcome is `MANIFESTATION_YES` and the case sits at
    `SANCTION_PROPOSED`, the IDEA ten-day cap bites immediately: the case's
    `proposed_sanction_days` is reduced to the lesser of its current value and
    the greater of zero and ten minus the student's
    `cumulative_suspension_days`, so the proposal can never push the student
    past ten total days and never below zero."

    Design: Corner/calculations/mdr_yes_caps_proposed_sanction_to_six
    """
    bundle = setup_case_with_auto_mdr(guardian_id="gm1", proposed_days=7)
    mdr = bundle["mdrs"][0]
    validate_success(api.schedule_manifestation_determination(
        mdr["id"], create_mdr_schedule_payload("2026-05-15T10:00:00Z"),
        SSD), 200)
    set_clock("2026-05-15T10:00:00Z")

    completed = validate_success(api.complete_manifestation_determination(
        mdr["id"], create_mdr_complete_payload("MANIFESTATION_YES"), SSD), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["outcome"] == "MANIFESTATION_YES"

    case2 = get_case(bundle["case2"]["id"])
    # min(7, max(0, 10 - 4)) == 6.
    assert case2["proposed_sanction_days"] == 6, (
        f"IDEA cap must reduce the proposal to 6, got "
        f"{case2['proposed_sanction_days']!r}")
    assert case2["status"] == "SANCTION_PROPOSED"
    assert case2["mdr_required"] is True


def test_mdr_complete_after_deadline_returns_409(api):
    """PRD §3.6: "Completion is lawful only from `SCHEDULED` and only on or
    before `due_at` — a late completion is rejected with
    `ERR_MDR_DEADLINE_PASSED`".

    Design: Corner/validations/mdr_complete_after_deadline_returns_409
    """
    bundle = setup_case_with_auto_mdr(guardian_id="gmdd", proposed_days=7)
    mdr = bundle["mdrs"][0]
    # Created at clock 2026-05-12T00:00Z -> due_at 2026-05-22T00:00Z.
    validate_success(api.schedule_manifestation_determination(
        mdr["id"], create_mdr_schedule_payload("2026-05-20T10:00:00Z"),
        SSD), 200)
    set_clock("2026-05-23T00:00:00Z")  # one day past due_at
    res = api.complete_manifestation_determination(
        mdr["id"], create_mdr_complete_payload("MANIFESTATION_NO"), SSD)
    validate_error(res, ApiErrorId.ERR_MDR_DEADLINE_PASSED, expected_status=409)


def test_mdr_manual_create_not_applicable_returns_409(api):
    """PRD §3.6: "The manual door is refused with `ERR_MDR_NOT_APPLICABLE`
    when the student's `disability_status` is `NONE` or the case is not on an
    applicable track".

    Design: Corner/validations/mdr_manual_create_not_applicable_returns_409
    """
    oc = create_offense_code_with_bands(bands=((1, 1, 3),))
    student = create_student(full_name="Stu NA", guardian_id="gna")
    case = create_classified_case(student["id"], oc["id"],
                                  "2026-05-04T08:00:00Z")
    res = api.create_manifestation_determination(case["id"], {}, SSD)
    validate_error(res, ApiErrorId.ERR_MDR_NOT_APPLICABLE, expected_status=409)


def test_mdr_manual_create_while_open_returns_409(api):
    """PRD §3.6: "and with `ERR_MDR_ALREADY_OPEN` when a determination already
    stands `PENDING` or `SCHEDULED` for the case."

    Design: Corner/validations/mdr_manual_create_while_open_returns_409
    """
    # The manual door requires an expulsion-track case (PRD §3.6). Set one up
    # and then open one manual MDR successfully; the second manual attempt
    # must surface ERR_MDR_ALREADY_OPEN (applicability is satisfied, so the
    # uniqueness rung fires per §2.9).
    bundle = setup_expulsion_referred_case(
        disability_status="SECTION_504", guardian_id="gmo")
    case_id = bundle["case"]["id"]
    first = validate_success(
        api.create_manifestation_determination(case_id, {}, SSD), 201)
    assert first["status"] == "PENDING"
    res = api.create_manifestation_determination(case_id, {}, SSD)
    validate_error(res, ApiErrorId.ERR_MDR_ALREADY_OPEN, expected_status=409)
