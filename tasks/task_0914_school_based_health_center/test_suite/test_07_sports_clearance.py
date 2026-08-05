"""The sports-physical clearance: its two validity windows, its deferral loop
and the gates that stand in front of it."""

from test_helpers import (
    REGISTRAR,
    ApiErrorId,
    assert_clearance,
    assert_same_date,
    get_clearance,
    get_student,
    reevaluate_clearance,
    set_financial_profile,
    setup_sports_physical_in_progress,
    student_version,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_cleared_determination_stores_the_pure_calendar_validity_window(api):
    """PRD §3.9: "The validity length is 365 days for `CLEARED` and 180 days for
    `CLEARED_WITH_RESTRICTIONS`; for `DEFERRED` and `NOT_CLEARED` there is no
    validity length at all, and both windows are stored as null.
    `unrestricted_valid_until` is the advisory, pure-calendar answer:
    `determination_date` advanced by the validity length."
    PRD §3.9: "A `CLEARED` determination made on 2026-05-10 therefore stores an
    `unrestricted_valid_until` of 2027-05-10 but a `valid_until` of 2026-07-31,
    because a school-year clearance cannot outlive the school year."

    Design: Difficulty/dual_variant_calc/clearance_validity_calendar_days_vs_school_year_capped
    """
    ctx = setup_sports_physical_in_progress(exemption="MEDICAL")
    assert get_student(ctx["student"]["id"])["immunization_compliance_status"] == "COMPLIANT"

    resp = api.create_sports_clearance(
        ctx["visit"]["id"],
        {"outcome": "CLEARED", "expected_student_version": student_version(ctx["student"]["id"])},
        ctx["clinician_headers"],
    )
    clearance = validate_success(resp, 201)

    assert_clearance(clearance)
    assert_same_date(clearance["determination_date"], "2026-05-10", "determination_date")
    assert_same_date(
        clearance["unrestricted_valid_until"], "2027-05-10", "unrestricted_valid_until"
    )
    assert clearance["status"] == "ACTIVE"
    assert clearance["reevaluation_count"] == 0


def test_operative_validity_is_capped_at_the_end_of_the_school_year(api):
    """PRD §3.9: "`valid_until` is the operative answer: the earlier of
    `unrestricted_valid_until` and the end date of the clearance's own school year
    — 2026-07-31 for `2025-2026` and 2027-07-31 for `2026-2027`."
    PRD §3.9: "The clearance copies `student_id` from the parent encounter and
    copies `school_year` from that encounter's enrollment; the copied year is what
    scopes both supersession and the validity cap."

    Design: Difficulty/dual_variant_calc/clearance_validity_calendar_days_vs_school_year_capped
    """
    ctx = setup_sports_physical_in_progress(exemption="MEDICAL")

    clearance = validate_success(
        api.create_sports_clearance(
            ctx["visit"]["id"],
            {
                "outcome": "CLEARED",
                "expected_student_version": student_version(ctx["student"]["id"]),
            },
            ctx["clinician_headers"],
        ),
        201,
    )

    assert clearance["school_year"] == "2025-2026"
    assert clearance["student_id"] == ctx["student"]["id"]
    assert_same_date(clearance["valid_until"], "2026-07-31", "valid_until")
    assert_same_date(
        clearance["unrestricted_valid_until"], "2027-05-10", "unrestricted_valid_until"
    )
    assert clearance["valid_until"] != clearance["unrestricted_valid_until"], (
        "The operative and advisory windows diverge whenever the school year ends first"
    )


def test_third_reevaluation_on_the_same_deferred_row_is_refused(api):
    """PRD §3.9: "Re-evaluation is accepted only from `PENDING_REEVALUATION`, only
    while `reevaluation_count` is strictly below 2 — a third attempt on the same
    row is `ERR_REEVALUATION_LIMIT_EXCEEDED`"
    PRD §3.9: "A re-evaluation carrying `DEFERRED` again keeps the row in
    `PENDING_REEVALUATION`, increments `reevaluation_count` by 1 and resets
    `determination_date` to the current clock date, which restarts the 30-day
    window from the new determination."

    Design: Corner/state_machines/clearance_deferral_loop_capped_at_two_reevaluations
    """
    ctx = setup_sports_physical_in_progress(exemption="MEDICAL")

    clearance = validate_success(
        api.create_sports_clearance(
            ctx["visit"]["id"],
            {
                "outcome": "DEFERRED",
                "expected_student_version": student_version(ctx["student"]["id"]),
            },
            ctx["clinician_headers"],
        ),
        201,
    )
    assert clearance["status"] == "PENDING_REEVALUATION"
    assert clearance["valid_until"] is None
    assert clearance["unrestricted_valid_until"] is None

    reevaluate_clearance(clearance["id"], ctx["clinician"]["id"], "DEFERRED")
    reevaluate_clearance(clearance["id"], ctx["clinician"]["id"], "DEFERRED")

    resp = api.reevaluate_sports_clearance(
        clearance["id"], {"outcome": "CLEARED"}, ctx["clinician_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_REEVALUATION_LIMIT_EXCEEDED.value, 409)

    reread = get_clearance(clearance["id"])
    assert reread["status"] == "PENDING_REEVALUATION"
    assert reread["reevaluation_count"] == 2
    assert reread["outcome"] == "DEFERRED"
    assert_same_date(reread["determination_date"], "2026-05-10", "determination_date")


def test_non_compliant_student_cannot_receive_a_determination(api):
    """PRD §3.9: "The student's `immunization_compliance_status` must be anything
    other than `NON_COMPLIANT` — both `COMPLIANT` and `PROVISIONAL` are acceptable
    — otherwise `ERR_IMMUNIZATION_NON_COMPLIANT`."
    PRD §2.6 rung 21: "The student's immunization compliance posture is anything
    other than `NON_COMPLIANT`, on `POST /sbhc/visits/{id}/sports-clearances` and
    `POST /sbhc/sports-clearances/{id}/re-evaluate`. Otherwise
    `ERR_IMMUNIZATION_NON_COMPLIANT` (409)."

    Design: Corner/errors/error_immunization_non_compliant_blocks_clearance
    """
    ctx = setup_sports_physical_in_progress(exemption=None)
    assert get_student(ctx["student"]["id"])["immunization_compliance_status"] == "NON_COMPLIANT"

    resp = api.create_sports_clearance(
        ctx["visit"]["id"],
        {"outcome": "CLEARED", "expected_student_version": student_version(ctx["student"]["id"])},
        ctx["clinician_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_IMMUNIZATION_NON_COMPLIANT.value, 409)

    _rows, meta = validate_paginated(
        api.list_sports_clearances(REGISTRAR, params={"visit_id": ctx["visit"]["id"]})
    )
    assert meta["total_count"] == 0, "A blocked determination must store no clearance row"


def test_clearance_create_with_a_stale_student_version_is_rejected(api):
    """PRD §2.7: "**Recording a sports-physical determination** (`POST
    /sbhc/visits/{id}/sports-clearances`) requires `expected_student_version` to
    match the student's current `version`. A new clearance supersedes the student's
    prior clearance for the same school year, and the student's `version` also
    advances whenever the immunization compliance posture that gates clearance
    changes — so a stale view may no longer justify the determination being
    recorded at all. Mismatch yields `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/clearance_create_with_stale_student_version_returns_stale_version
    """
    ctx = setup_sports_physical_in_progress(exemption="MEDICAL")
    stale_version = student_version(ctx["student"]["id"])

    fresh = set_financial_profile(
        ctx["student"]["id"],
        household_income_annual_cents=3_000_000,
        household_size=4,
        payer_route="SELF_PAY",
    )
    assert fresh["version"] != stale_version

    stale_resp = api.create_sports_clearance(
        ctx["visit"]["id"],
        {"outcome": "CLEARED", "expected_student_version": stale_version},
        ctx["clinician_headers"],
    )
    validate_error(stale_resp, ApiErrorId.ERR_STALE_VERSION.value, 412)

    accepted = validate_success(
        api.create_sports_clearance(
            ctx["visit"]["id"],
            {"outcome": "CLEARED", "expected_student_version": fresh["version"]},
            ctx["clinician_headers"],
        ),
        201,
    )

    assert accepted["status"] == "ACTIVE"
    assert_same_date(accepted["valid_until"], "2026-07-31", "valid_until")

    _rows, meta = validate_paginated(
        api.list_sports_clearances(REGISTRAR, params={"student_id": ctx["student"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"The rejected determination must store no row, got {meta['total_count']} clearances"
    )
