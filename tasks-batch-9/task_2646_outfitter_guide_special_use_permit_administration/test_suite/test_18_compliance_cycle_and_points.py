"""The compliance dimension as a cycle, and the two inclusive point thresholds.

Covers the re-entrant COMPLIANT / PROBATION / NONCOMPLIANT run driven only by
system re-derivations, and the 5-point and 12-point boundaries probed from
directly below and directly on them.
"""
from test_helpers import (
    ApiErrorId,
    OFFICER_USER_ID,
    create_outfitter,
    create_published_assessment,
    create_screened_application,
    create_use_area,
    cure_action,
    decide_appeal,
    appeal_action,
    file_bond,
    file_insurance_certificate,
    issue_noncompliance_action,
    issue_permit,
    list_noncompliance_actions,
    read_permit,
    set_clock,
    setup_issued_permit,
    validate_error,
    api_client,
)

BETA = {
    "legal_name": "Beta Trails Co",
    "ein": "410000002",
    "contact_email": "ops@beta.example",
    "prequalification_insurance_verified": True,
}
LONG_TERM = {"term_start_date": "2027-01-01", "term_end_date": "2029-12-31"}


def _compliant_permit():
    """An ISSUED 200-day permit standing in COMPLIANT with insurance on file, so
    that points are the only live driver of the compliance derivation."""
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides=dict(LONG_TERM),
    )
    file_insurance_certificate(context["permit"]["id"], context["outfitter"]["id"])
    permit = read_permit(context["permit"]["id"])
    assert permit["insurance_current"] is True
    assert permit["fee_delinquent"] is False
    assert permit["open_noncompliance_points"] == 0
    assert permit["compliance_status"] == "COMPLIANT"
    assert permit["administrative_status"] == "ISSUED"
    return context


def _cite(context, severity, action_type, provision):
    return issue_noncompliance_action(
        context["permit"]["id"],
        severity=severity,
        action_type=action_type,
        cited_provision=provision,
        cure_deadline_date="2027-06-30",
    )


def _signals(context):
    permit = read_permit(context["permit"]["id"])
    return permit["open_noncompliance_points"], permit["compliance_status"], permit[
        "administrative_status"
    ]


def test_the_compliance_dimension_is_re_entered_from_both_directions_in_one_run():
    """PRD §3.8: "The `compliance_status` dimension is never set by a request. It is re-derived, by
    one rule, after any change to `open_noncompliance_points`, `insurance_current`, `bond_current`
    or `fee_delinquent`, and the rule is evaluated in order with the first match winning. If
    `open_noncompliance_points` is at or above **12**, the permit is `NONCOMPLIANT`. Otherwise, if
    `open_noncompliance_points` is at or above **5**, or `insurance_current` is false, or
    `fee_delinquent` is true, the permit is on `PROBATION`. Otherwise it is `COMPLIANT`."
    PRD §3.8: "The dimension is cyclic, and all six moves between its three values are reachable"
    PRD §3.8: "A cured action is terminal and stops contributing points, so a cure can pull the
    permit back below a threshold; it never auto-reinstates a suspended permit."
    PRD §3.8: "Leaving `NONCOMPLIANT` never auto-reinstates, and entering or leaving `PROBATION`
    never changes `administrative_status` at all."
    PRD §3.8: "`points` is derived from severity: 2 for `MINOR`, 5 for `MODERATE`, 10 for `MAJOR`."

    Design: Difficulty/non_linear_state_machine/permit_compliance_cycle_probation_and_back
    """
    context = _compliant_permit()
    holder = context["holder_headers"]

    first = _cite(context, "MODERATE", "WARNING", "operating plan clause 4 - stock containment")
    assert first["points"] == 5
    assert first["status"] == "ISSUED"
    assert first["issued_by_user_id"] == OFFICER_USER_ID
    assert _signals(context) == (5, "PROBATION", "ISSUED"), "COMPLIANT -> PROBATION"

    cured_first = cure_action(first["id"], context["outfitter"]["id"])
    assert cured_first["status"] == "CURED"
    assert _signals(context) == (0, "COMPLIANT", "ISSUED"), "PROBATION -> COMPLIANT"

    second = _cite(context, "MODERATE", "WARNING", "operating plan clause 7 - greywater")
    assert _signals(context) == (5, "PROBATION", "ISSUED"), "the state is re-entered a second time"
    third = _cite(context, "MODERATE", "WARNING", "operating plan clause 9 - campsite nights")
    assert _signals(context) == (10, "PROBATION", "ISSUED")

    fourth = _cite(context, "MINOR", "WARNING", "operating plan clause 2 - signage")
    assert fourth["points"] == 2
    assert _signals(context) == (12, "NONCOMPLIANT", "ISSUED"), "PROBATION -> NONCOMPLIANT at 12"

    cured_fourth = cure_action(fourth["id"], context["outfitter"]["id"])
    assert cured_fourth["status"] == "CURED"
    assert _signals(context) == (10, "PROBATION", "ISSUED"), (
        "NONCOMPLIANT -> PROBATION descends the same edge it climbed, "
        "and the administrative dimension is never touched"
    )

    validate_error(
        api_client.cure_noncompliance_action(
            fourth["id"], {"corrective_summary": "Signage checked again"}, holder
        ),
        ApiErrorId.ERR_ACTION_NOT_APPEALABLE,
    )

    rows, meta = list_noncompliance_actions(context["permit"]["id"])
    assert meta["total_count"] == 4
    assert [row["status"] for row in rows] == ["CURED", "ISSUED", "ISSUED", "CURED"], (
        "actions list oldest first, and only the cured rows stopped contributing points"
    )
    assert [row["id"] for row in rows] == [
        first["id"], second["id"], third["id"], fourth["id"]
    ]


def test_one_major_citation_jumps_straight_past_probation_and_a_rescission_walks_back():
    """PRD §3.8: "The dimension is cyclic, and all six moves between its three values are
    reachable, including the jump from `COMPLIANT` straight to `NONCOMPLIANT` when one major
    citation carries a permit from below 5 points to 12 or more."
    PRD §3.8: "an appealed action **keeps contributing its points** while the appeal is pending,
    because appealing is not a stay."
    PRD §3.8: "`RESCINDED` drops the action's points, so the point total is recomputed downward and
    compliance re-derived."
    PRD §3.8: "Both thresholds are inclusive comparisons: 12 points is noncompliant, 11 is not; 5
    points is probation, 4 is not."
    PRD §3.8: "An `action_type` of `SUSPENSION`, by contrast, does not suspend anything by itself;
    suspension arrives only through the point threshold or an officer's explicit order."

    Design: Difficulty/non_linear_state_machine/permit_compliance_cycle_probation_and_back
    """
    context = _compliant_permit()

    _cite(context, "MINOR", "WARNING", "36 CFR 251.56(a) sanitation")
    assert _signals(context) == (2, "COMPLIANT", "ISSUED")
    _cite(context, "MINOR", "WARNING", "36 CFR 251.56(a) signage")
    assert _signals(context) == (4, "COMPLIANT", "ISSUED"), "4 points is not probation"

    major = _cite(context, "MAJOR", "SUSPENSION", "36 CFR 251.60(a) unauthorized structure")
    assert major["points"] == 10
    assert _signals(context) == (14, "NONCOMPLIANT", "ISSUED"), (
        "COMPLIANT straight to NONCOMPLIANT, and the SUSPENSION instrument suspends nothing"
    )

    appealed = appeal_action(major["id"], context["outfitter"]["id"])
    assert appealed["status"] == "APPEALED"
    assert _signals(context) == (14, "NONCOMPLIANT", "ISSUED"), "appealing is not a stay"

    decided = decide_appeal(major["id"], "RESCINDED")
    assert decided["status"] == "RESCINDED"
    assert _signals(context) == (4, "COMPLIANT", "ISSUED"), (
        "NONCOMPLIANT straight back to COMPLIANT, skipping probation on the way down too"
    )

    last = _cite(context, "MINOR", "WARNING", "36 CFR 251.56(a) stock")
    assert _signals(context) == (6, "PROBATION", "ISSUED"), "5 points is probation, so 6 is too"
    cure_action(last["id"], context["outfitter"]["id"])
    assert _signals(context) == (4, "COMPLIANT", "ISSUED")

    permit = read_permit(context["permit"]["id"])
    assert permit["suspension_count"] == 0
    assert permit["suspended_until_date"] is None
    assert permit["suspension_reason_code"] is None
    _rows, meta = list_noncompliance_actions(
        context["permit"]["id"], params={"status": "ISSUED"}
    )
    assert meta["total_count"] == 2, "the rescinded and cured rows survive under other statuses"


def _two_assured_permits():
    """Two ISSUED 200-day permits on one area, each carrying the exact required
    assurance, so `insurance_current` and `bond_current` are true and points are
    the only live term in the compliance derivation."""
    set_clock()
    area = create_use_area()
    create_published_assessment(area["id"], determined_capacity_service_days=900)
    holders = {
        "alpine": (create_outfitter(), "RIVER_FLOAT"),
        "beta": (create_outfitter(**BETA), "HUNTING"),
    }
    permits = {}
    for key, (outfitter, activity) in holders.items():
        application = create_screened_application(
            outfitter["id"], area["id"],
            requested_service_days=200, proposed_activity_type=activity,
        )
        permit = issue_permit(application["id"], **LONG_TERM)
        file_insurance_certificate(permit["id"], outfitter["id"])
        file_bond(permit["id"], outfitter["id"])
        fresh = read_permit(permit["id"])
        assert fresh["insurance_current"] is True
        assert fresh["bond_current"] is True
        assert fresh["fee_delinquent"] is False
        assert fresh["open_noncompliance_points"] == 0
        assert fresh["compliance_status"] == "COMPLIANT"
        permits[key] = fresh
    return permits


def _cite_on(permit_id, severity, action_type, provision):
    return issue_noncompliance_action(
        permit_id, severity=severity, action_type=action_type,
        cited_provision=provision, cure_deadline_date="2027-03-01",
    )


def _read_points(permit_id):
    permit = read_permit(permit_id)
    return permit["open_noncompliance_points"], permit["compliance_status"], permit[
        "administrative_status"
    ]


def test_eleven_points_from_four_actions_is_probation_and_never_noncompliant():
    """PRD §3.8: "If `open_noncompliance_points` is at or above **12**, the permit is
    `NONCOMPLIANT`. Otherwise, if `open_noncompliance_points` is at or above **5**, or
    `insurance_current` is false, or `fee_delinquent` is true, the permit is on `PROBATION`.
    Otherwise it is `COMPLIANT`. Both thresholds are inclusive comparisons: 12 points is
    noncompliant, 11 is not; 5 points is probation, 4 is not."
    PRD §3.8: "`points` is derived from severity: 2 for `MINOR`, 5 for `MODERATE`, 10 for `MAJOR`."
    PRD §3.8: "Note that `bond_current` triggers the re-derivation but is not a term in it: a lapsed
    bond does not by itself make a permit non-compliant, it blocks activation and reinstatement
    instead."

    Design: Difficulty/boundary_precision_check/noncompliance_point_threshold_twelve_boundary
    """
    permits = _two_assured_permits()
    alpine = permits["alpine"]["id"]

    first = _cite_on(alpine, "MINOR", "WARNING", "36 CFR 251.56(a) sanitation")
    assert first["points"] == 2
    assert _read_points(alpine) == (2, "COMPLIANT", "ISSUED")

    second = _cite_on(alpine, "MINOR", "WARNING", "36 CFR 251.56(a) campsite")
    assert second["points"] == 2
    assert _read_points(alpine) == (4, "COMPLIANT", "ISSUED"), "4 points is not probation"

    _cite_on(alpine, "MINOR", "WARNING", "36 CFR 251.56(a) stock")
    assert _read_points(alpine) == (6, "PROBATION", "ISSUED"), (
        "the 5-point boundary is crossed between 4 and 6, so >= 5 is inclusive"
    )

    fourth = _cite_on(alpine, "MODERATE", "WARNING", "36 CFR 251.56(a) reporting")
    assert fourth["points"] == 5
    assert _read_points(alpine) == (11, "PROBATION", "ISSUED"), (
        "eleven points is one short of the threshold and stays on probation"
    )

    permit = read_permit(alpine)
    assert permit["suspension_count"] == 0
    assert permit["suspended_until_date"] is None
    assert permit["insurance_current"] is True
    assert permit["bond_current"] is True
    assert permit["fee_delinquent"] is False

    _rows, meta = list_noncompliance_actions(alpine)
    assert meta["total_count"] == 4
    assert _read_points(permits["beta"]["id"]) == (0, "COMPLIANT", "ISSUED"), (
        "points are summed per permit, not across the area"
    )


def test_exactly_twelve_points_from_three_actions_is_noncompliant_on_the_compliance_dimension():
    """PRD §3.8: "Both thresholds are inclusive comparisons: 12 points is noncompliant, 11 is not; 5
    points is probation, 4 is not."
    PRD §3.8: "`points` is derived from severity: 2 for `MINOR`, 5 for `MODERATE`, 10 for `MAJOR`."
    PRD §3.8: "The permit's `open_noncompliance_points` is a rolling sum, recomputed from scratch
    after every issuance, cure, appeal decision and compliance re-derivation."
    PRD §3.8: "Entering `NONCOMPLIANT` while `administrative_status` is `ACTIVE` suspends the
    permit, with `suspension_reason_code` `POINTS_THRESHOLD`"

    Design: Difficulty/boundary_precision_check/noncompliance_point_threshold_twelve_boundary
    """
    permits = _two_assured_permits()
    alpine = permits["alpine"]["id"]
    beta = permits["beta"]["id"]

    _cite_on(beta, "MINOR", "WARNING", "36 CFR 251.56(a) sanitation")
    assert _read_points(beta) == (2, "COMPLIANT", "ISSUED")
    _cite_on(beta, "MODERATE", "WARNING", "36 CFR 251.56(a) resource damage")
    assert _read_points(beta) == (7, "PROBATION", "ISSUED")
    _cite_on(beta, "MODERATE", "WARNING", "36 CFR 251.56(a) reporting")
    assert _read_points(beta) == (12, "NONCOMPLIANT", "ISSUED"), (
        "the comparison is >= 12, not > 12, and the permit was never ACTIVE so nothing suspends"
    )

    beta_permit = read_permit(beta)
    assert beta_permit["suspension_count"] == 0
    assert beta_permit["suspended_until_date"] is None
    assert beta_permit["suspension_reason_code"] is None

    for provision in (
        "36 CFR 251.56(a) sanitation",
        "36 CFR 251.56(a) campsite",
        "36 CFR 251.56(a) stock",
    ):
        _cite_on(alpine, "MINOR", "WARNING", provision)
    _cite_on(alpine, "MODERATE", "WARNING", "36 CFR 251.56(a) reporting")

    _alpine_rows, alpine_meta = list_noncompliance_actions(alpine)
    _beta_rows, beta_meta = list_noncompliance_actions(beta)
    assert alpine_meta["total_count"] == 4
    assert beta_meta["total_count"] == 3
    assert _read_points(alpine) == (11, "PROBATION", "ISSUED")
    assert _read_points(beta) == (12, "NONCOMPLIANT", "ISSUED"), (
        "four actions sum to 11 while three sum to 12, so the total is driven by severity "
        "rather than counted per action"
    )
