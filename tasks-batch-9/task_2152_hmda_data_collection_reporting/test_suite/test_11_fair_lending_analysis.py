"""Fair lending: the pinned three-step disparity index, its banding and the
empty-group refusal."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_fair_lending_analysis,
    assert_significance_banding,
    create_fair_lending_payload,
    create_institution,
    make_compliance_analyst_headers,
    setup_analysed_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def _five_record_race_population(institution_id):
    """Two control records (one originated, one denied) and three protected records
    (one originated, two denied), all decided inside the analysis period."""
    setup_analysed_application(institution_id, "WHITE", "ORIGINATED", "2026-03-10T00:00:00Z")
    setup_analysed_application(institution_id, "WHITE", "DENIED", "2026-03-11T00:00:00Z",
                               income_thousands=90)
    setup_analysed_application(institution_id, "BLACK", "ORIGINATED", "2026-03-12T00:00:00Z",
                               income_thousands=105)
    setup_analysed_application(institution_id, "BLACK", "DENIED", "2026-03-13T00:00:00Z",
                               income_thousands=85)
    setup_analysed_application(institution_id, "BLACK", "DENIED", "2026-03-14T00:00:00Z",
                               income_thousands=80)


def test_a_zero_control_denial_rate_caps_the_index_and_escalates(api):
    """PRD §3.9: "Third, `disparity_index` is computed **from those two
    already-rounded rates**, not from the raw ratios: if both rates are 0.00, the
    index is 100.00, because two groups that were never denied are treated as
    identical; if only the control rate is 0.00, the index is capped at 999.99,
    because dividing by a zero control rate is undefined and the platform reports
    the maximum rather than failing; otherwise the index is
    `protected_denial_rate_pct` divided by `control_denial_rate_pct`, multiplied by
    100, and rounded to two decimal places."
    PRD §3.9: "`significance_flag` bands the index: `SEVERE` when `disparity_index`
    is at least 200.0, otherwise `ELEVATED` when it is at least 125.0, otherwise
    `NOT_SIGNIFICANT`. The analysis then resolves its own status in the same
    request — an analysis flagged `SEVERE` settles `COMPUTED → ESCALATED`, while
    one flagged `ELEVATED` or `NOT_SIGNIFICANT` settles `COMPUTED → CLEARED`."

    Design: Corner/state_machines/fair_lending_severe_disparity_auto_escalates
    """
    institution = create_institution()
    setup_analysed_application(institution["id"], "WHITE", "ORIGINATED", "2026-03-10T00:00:00Z")
    setup_analysed_application(institution["id"], "BLACK", "DENIED", "2026-03-11T00:00:00Z",
                               income_thousands=70)

    data = validate_success(
        api.create_fair_lending_analysis(
            create_fair_lending_payload(institution["id"]),
            make_compliance_analyst_headers(),
        ),
        201,
    )
    assert_fair_lending_analysis(data)
    assert data["control_total"] == 1
    assert data["control_denied"] == 0
    assert data["control_denial_rate_pct"] == 0.00
    assert data["protected_denial_rate_pct"] == 100.00
    assert data["disparity_index"] == 999.99
    assert data["significance_flag"] == "SEVERE"
    assert data["status"] == "ESCALATED"
    assert data["analysis_index"] == 1


def test_an_empty_protected_group_makes_the_analysis_meaningless(api):
    """PRD §3.9: "`control_total` and `protected_total` hold the two group sizes,
    and `control_denied` and `protected_denied` hold the denials within each. If
    either group is empty the analysis is refused with `ERR_EMPTY_CONTROL_GROUP`,
    since a disparity against nothing is meaningless."

    Design: Corner/validations/fair_lending_with_an_empty_protected_group_rejected
    """
    institution = create_institution()
    setup_analysed_application(institution["id"], "WHITE", "ORIGINATED", "2026-03-10T00:00:00Z")

    validate_error(
        api.create_fair_lending_analysis(
            create_fair_lending_payload(institution["id"]),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_EMPTY_CONTROL_GROUP.value,
    )

    rows, meta = validate_paginated(
        api.list_institution_fair_lending_analyses(
            institution["id"], TEST_USERS["examiner_headers"]
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_each_denial_rate_is_rounded_before_the_disparity_division(api):
    """PRD §3.9: "First, `control_denial_rate_pct` is `control_denied` divided by
    `control_total`, multiplied by 100, and rounded to two decimal places. Second,
    `protected_denial_rate_pct` is `protected_denied` divided by `protected_total`,
    multiplied by 100, and rounded to two decimal places. Third, `disparity_index`
    is computed **from those two already-rounded rates**, not from the raw ratios:
    if both rates are 0.00, the index is 100.00, because two groups that were never
    denied are treated as identical; if only the control rate is 0.00, the index is
    capped at 999.99, because dividing by a zero control rate is undefined and the
    platform reports the maximum rather than failing; otherwise the index is
    `protected_denial_rate_pct` divided by `control_denial_rate_pct`, multiplied by
    100, and rounded to two decimal places."
    PRD §3.9: "Dividing the raw ratios and rounding once at the end yields a
    different number and is explicitly not what this system computes."

    Design: Difficulty/combinatorial_formula/fair_lending_disparity_rounds_each_rate_before_dividing
    """
    institution = create_institution()
    _five_record_race_population(institution["id"])

    data = validate_success(
        api.create_fair_lending_analysis(
            create_fair_lending_payload(institution["id"]),
            make_compliance_analyst_headers(),
        ),
        201,
    )
    assert data["control_denial_rate_pct"] == 50.00
    assert data["protected_denial_rate_pct"] == 66.67
    assert data["disparity_index"] == 133.34, (
        "the index divides the two already-rounded rates, not the raw ratios"
    )
    assert data["disparity_index"] != 133.33


def test_the_group_totals_and_banding_of_the_rounded_disparity(api):
    """PRD §3.9: "The analysis universe is every register record of the institution
    with an `action_taken` recorded, whose `action_taken_date` falls on or after
    `period_start` and on or before `period_end`, whose `is_superseded` flag is
    false, and whose `lar_status` is anything other than `EXCLUDED`."
    PRD §3.9: "A record counts as denied when its `action_taken` reads either
    `DENIED` or `PREAPPROVAL_DENIED`."
    PRD §3.9: "`significance_flag` bands the index: `SEVERE` when `disparity_index`
    is at least 200.0, otherwise `ELEVATED` when it is at least 125.0, otherwise
    `NOT_SIGNIFICANT`. The analysis then resolves its own status in the same
    request — an analysis flagged `SEVERE` settles `COMPUTED → ESCALATED`, while
    one flagged `ELEVATED` or `NOT_SIGNIFICANT` settles `COMPUTED → CLEARED`."

    Design: Difficulty/combinatorial_formula/fair_lending_disparity_rounds_each_rate_before_dividing
    """
    institution = create_institution()
    _five_record_race_population(institution["id"])

    data = validate_success(
        api.create_fair_lending_analysis(
            create_fair_lending_payload(institution["id"]),
            make_compliance_analyst_headers(),
        ),
        201,
    )
    assert_fair_lending_analysis(data)
    assert data["control_total"] == 2
    assert data["control_denied"] == 1
    assert data["protected_total"] == 3
    assert data["protected_denied"] == 2
    assert data["significance_flag"] == "ELEVATED"
    assert data["status"] == "CLEARED"
    assert_significance_banding(data)
