"""Progressive sanction matrix: bands, cap, override, OCC on proposals."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    assert_discipline_case,
    create_offense_code_payload, create_sanction_band_payload,
    create_classify_payload, create_sanction_payload,
    set_clock, create_offense_code, create_offense_code_with_bands,
    add_sanction_band, create_student, create_case, classify_case,
    create_classified_case, propose_sanction, get_case,
    make_school_admin_headers,
    TEST_USERS, ApiErrorId,
)

ADMIN = TEST_USERS["district_admin_headers"]
REF = TEST_USERS["school_referrer_headers"]
CLS = TEST_USERS["school_classifier_headers"]


def test_duplicate_sanction_band_returns_409(api):
    """PRD §3.1: "Every band belongs to its offense code through
    `offense_code_id`, and only one band may exist for a given code-and-index
    pair — a second band for the same pair is rejected with
    `ERR_DUPLICATE_BAND`."

    Design: Corner/validations/duplicate_sanction_band_returns_409
    """
    oc = create_offense_code_with_bands(bands=((1, 1, 3),))
    res = api.create_sanction_band(
        oc["id"], create_sanction_band_payload(occurrence_index=1, min_days=2,
                                               max_days=4), ADMIN)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_BAND, expected_status=409)

    bands = validate_success(api.list_sanction_bands(oc["id"], ADMIN), 200)
    first = [b for b in bands if b["occurrence_index"] == 1]
    assert len(first) == 1
    assert first[0]["min_days"] == 1 and first[0]["max_days"] == 3, (
        "the first band must be unchanged by the rejected duplicate")


def test_sanction_without_defined_band_returns_409(api):
    """PRD §3.3: "First, the band applied is the one belonging to the case's
    offense code whose `occurrence_index` equals the lesser of the case's
    stored index and three; if no such band exists the proposal is rejected
    with `ERR_BAND_NOT_DEFINED`."

    Design: Corner/validations/sanction_without_defined_band_returns_409
    """
    oc = create_offense_code()  # no bands at all
    student = create_student(full_name="Stu NoBand", guardian_id="gnb")
    case = create_classified_case(student["id"], oc["id"], "2026-05-04T08:00:00Z")

    res = api.propose_sanction(
        case["id"], create_sanction_payload(2, case["version"]), CLS)
    validate_error(res, ApiErrorId.ERR_BAND_NOT_DEFINED, expected_status=409)


def test_sanction_above_band_without_justification_returns_422(api):
    """PRD §3.3: "Days outside the range are the matrix's concession to
    administrator discretion: the request is rejected with
    `ERR_SANCTION_OUT_OF_RANGE` unless a non-empty `override_justification`
    accompanies it, in which case the proposal stands with `sanction_override`
    set to true and the justification retained on the case."

    Design: Corner/validations/sanction_above_band_without_justification_returns_422
    """
    oc = create_offense_code_with_bands(bands=((1, 1, 3),))
    student = create_student(full_name="Stu Range", guardian_id="gr1")
    case = create_classified_case(student["id"], oc["id"], "2026-05-04T08:00:00Z")

    # 5 > band max 3 and no override_justification supplied.
    res = api.propose_sanction(
        case["id"], create_sanction_payload(5, case["version"]), CLS)
    validate_error(res, ApiErrorId.ERR_SANCTION_OUT_OF_RANGE, expected_status=422)


def test_sanction_cap_ten_days_boundary(api):
    """PRD §3.3: "Next, the district's absolute cap applies: any proposal of
    more than ten days is rejected with `ERR_SANCTION_EXCEEDS_CAP`, and this
    cap is evaluated before the band range so that an over-cap day count
    surfaces the cap error rather than a range error."

    Design: Corner/calculations/sanction_cap_ten_days_boundary
    """
    oc = create_offense_code_with_bands(bands=((1, 1, 3),))
    student = create_student(full_name="Stu Cap", guardian_id="gc1")
    case = create_classified_case(student["id"], oc["id"], "2026-05-04T08:00:00Z")

    # 11 > cap 10: rejected even with a justification.
    res = api.propose_sanction(
        case["id"],
        create_sanction_payload(11, case["version"],
                                override_justification="extreme case"),
        CLS)
    validate_error(res, ApiErrorId.ERR_SANCTION_EXCEEDS_CAP, expected_status=422)
    settled = get_case(case["id"])
    assert settled["status"] == "CLASSIFIED"
    assert settled["version"] == case["version"], (
        "a rejected proposal must not advance the case version")

    # Exactly 10 is within the cap; outside the band [1,3], the justification
    # carries it as an administrator-discretion override.
    accepted = validate_success(api.propose_sanction(
        case["id"],
        create_sanction_payload(10, case["version"],
                                override_justification="extreme case"),
        CLS), 200)
    assert accepted["proposed_sanction_days"] == 10
    assert accepted["sanction_override"] is True


def test_occ_sanction_adjust_stale_version_returns_412(api):
    """PRD §3.3: "Adjustment runs the identical band, cap, and override checks
    and the identical OCC guard, so an administrator iterating on a proposal
    against a stale `expected_case_version` is refused with
    `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_layers/occ_sanction_adjust_stale_version_returns_412
    """
    oc = create_offense_code_with_bands(bands=((1, 1, 3),))
    student = create_student(full_name="Stu OCC2", guardian_id="gocc2")
    case = create_classified_case(student["id"], oc["id"], "2026-05-04T08:00:00Z")

    proposed = validate_success(api.propose_sanction(
        case["id"], create_sanction_payload(2, case["version"]), CLS), 200)
    assert proposed["version"] == case["version"] + 1, (
        "each accepted proposal increments the case version by one (PRD §3.3)")

    adjusted = validate_success(api.propose_sanction(
        case["id"], create_sanction_payload(3, proposed["version"]), CLS), 200)
    assert adjusted["version"] == proposed["version"] + 1
    assert adjusted["proposed_sanction_days"] == 3

    # Replay the version captured before the accepted adjustment: stale.
    res = api.propose_sanction(
        case["id"], create_sanction_payload(3, proposed["version"]), CLS)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    settled = get_case(case["id"])
    assert settled["proposed_sanction_days"] == 3, (
        "the rejected stale adjustment must change nothing")
    assert settled["version"] == adjusted["version"]


# ─── Difficulty: combinatorial sanction formula ───────

def _setup_combo_case(api):
    """DISRUPTION code with band occ1 [1,3]; a NONE-disability student with no
    priors; a case classified (occurrence 1) at clock 2026-05-02."""
    set_clock("2026-05-02T00:00:00Z")
    oc = create_offense_code_with_bands(bands=((1, 1, 3),))
    student = create_student(full_name="Stu Combo",
                             date_of_birth="2009-05-01T00:00:00Z",
                             grade_level=11, demographic_group="HISPANIC",
                             guardian_id="guard_c")
    case = create_classified_case(student["id"], oc["id"],
                                  "2026-05-02T00:00:00Z",
                                  description="hallway disruption")
    return oc, student, case


def test_sanction_inside_band_clears_override_and_skips_mdr(api):
    """PRD §3.3: "Days inside the range clear the check with
    `sanction_override` recorded as false."
    PRD §3.3: "`mdr_required` is true exactly when the student's
    `disability_status` is `IEP` or `SECTION_504` and the sum of the student's
    `cumulative_suspension_days` and the proposed days is strictly greater
    than ten — a combined total of exactly ten does not trigger it."

    Design: Difficulty/combinatorial_formula/sanction_band_clamp_with_override_and_threshold_branch
    """
    oc, student, case = _setup_combo_case(api)

    proposed = validate_success(api.propose_sanction(
        case["id"],
        create_sanction_payload(3, case["version"], sanction_type="IN_SCHOOL"),
        CLS), 200)
    assert proposed["sanction_override"] is False, (
        "3 days sits inside band [1,3], so no override is recorded")
    assert proposed["proposed_sanction_days"] == 3
    assert proposed["proposed_sanction_type"] == "IN_SCHOOL"
    # disability NONE short-circuits the ten-day threshold branch.
    assert proposed["mdr_required"] is False
    assert proposed["version"] == case["version"] + 1


def test_sanction_outside_band_with_justification_sets_override(api):
    """PRD §3.3: "the request is rejected with `ERR_SANCTION_OUT_OF_RANGE`
    unless a non-empty `override_justification` accompanies it, in which case
    the proposal stands with `sanction_override` set to true and the
    justification retained on the case."
    PRD §3.3: "the same write serves as the adjustment self-loop
    (`SANCTION_PROPOSED` → `SANCTION_PROPOSED`): it replaces
    `proposed_sanction_days`, `proposed_sanction_type`, `sanction_override`,
    and `proposed_at`".

    Design: Difficulty/combinatorial_formula/sanction_band_clamp_with_override_and_threshold_branch
    """
    oc, student, case = _setup_combo_case(api)
    proposed = validate_success(api.propose_sanction(
        case["id"],
        create_sanction_payload(3, case["version"], sanction_type="IN_SCHOOL"),
        CLS), 200)

    # Adjust to 6 days: above band max 3 but within the absolute cap of 10,
    # with administrator-discretion justification.
    adjusted = validate_success(api.propose_sanction(
        case["id"],
        create_sanction_payload(
            6, proposed["version"], sanction_type="OUT_OF_SCHOOL",
            override_justification="repeat severe disruption with safety risk"),
        CLS), 200)
    assert adjusted["sanction_override"] is True
    assert adjusted["proposed_sanction_days"] == 6
    assert adjusted["proposed_sanction_type"] == "OUT_OF_SCHOOL"
    assert adjusted["override_justification"] == (
        "repeat severe disruption with safety risk")
    assert adjusted["mdr_required"] is False
    assert adjusted["version"] == proposed["version"] + 1
