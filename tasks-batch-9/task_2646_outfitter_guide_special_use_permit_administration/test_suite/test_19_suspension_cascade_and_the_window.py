"""The point-threshold suspension, five links deep, and the rolling point window.

Covers the cascade that reaches from one citation through both permit
dimensions into the authorization rows and the holder, the suspension length
multiplier behind an upheld major citation, the 1095-day window with its
inclusive lower bound, and the severity-to-instrument matrix.
"""
from test_helpers import (
    ApiErrorId,
    OFFICER_USER_ID,
    appeal_action,
    cure_action,
    decide_appeal,
    issue_noncompliance_action,
    list_noncompliance_actions,
    list_permit_authorizations,
    read_allocation_summary,
    read_guide,
    read_outfitter,
    read_permit,
    run_sweep,
    set_clock,
    setup_active_permit,
    setup_issued_permit,
    validate_error,
    validate_success,
    api_client,
    TEST_USERS,
)

OFFICER = TEST_USERS["authorized_officer_headers"]
LONG_TERM = {"term_start_date": "2027-01-01", "term_end_date": "2029-12-31"}


def _active_permit_on_probation():
    """An ACTIVE permit with a staffed roster of twelve client capacity, current
    insurance and bond, and two MODERATE citations already standing — ten points,
    PROBATION, and two points short of the threshold."""
    context = setup_active_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides=dict(LONG_TERM),
    )
    context["actions"] = [
        issue_noncompliance_action(
            context["permit"]["id"], severity="MODERATE", action_type="WARNING",
            cited_provision=provision, cure_deadline_date="2027-12-01",
        )
        for provision in (
            "operating plan clause 4 - stock containment",
            "operating plan clause 7 - greywater",
        )
    ]
    permit = read_permit(context["permit"]["id"])
    assert permit["administrative_status"] == "ACTIVE"
    assert permit["compliance_status"] == "PROBATION"
    assert permit["open_noncompliance_points"] == 10
    assert permit["authorized_client_capacity_total"] == 12
    assert permit["suspension_count"] == 0
    assert read_outfitter(context["outfitter"]["id"])["status"] == "PERMITTED"
    return context


def test_one_major_citation_suspends_the_permit_and_collapses_the_roster_and_the_holder():
    """PRD §3.8: "Entering `NONCOMPLIANT` while `administrative_status` is `ACTIVE` suspends the
    permit, with `suspension_reason_code` `POINTS_THRESHOLD` and a suspension length of 30 days
    multiplied by one plus the count of that permit's `MAJOR` actions in `UPHELD` — so a first
    threshold breach suspends for 30 days, and a breach behind one upheld major citation for 60."
    PRD §3.8: "Whatever the trigger, suspension increments `suspension_count`, stamps the date and
    reason, revokes every `AUTHORIZED` authorization on the permit with reason `PERMIT_SUSPENDED` so
    that `authorized_client_capacity_total` recomputes to 0, and then recomputes the holder's
    `active_permit_count` and re-derives its `status`, which falls from `PERMITTED` to `SUSPENDED`
    once the holder has no active permits left and at least one suspended one."
    PRD §2.9: "a revoked guide authorization keeps its own frozen capacity figure on the row for the
    audit record but stops counting toward the permit's total"
    PRD §3.1: "A `LEAD` holding `WFR` with seven completed seasons therefore carries 8 (the lesser
    of 8 and 8) plus 2 (seven divided by three, floored, capped at 2), for 10."
    PRD §2.7: "`committed_service_days` is the sum of `authorized_service_days` over every `Permit`
    in the area whose `administrative_status` is `ISSUED`, `ACTIVE` or `SUSPENDED`; a `REVOKED`,
    `EXPIRED` or `CLOSED` permit releases its days."

    Design: Difficulty/transitive_cascade/noncompliance_points_suspension_cascade_depth_five
    """
    context = _active_permit_on_probation()
    permit_id = context["permit"]["id"]
    lead, assistant = context["guides"]
    set_clock("2027-09-05T00:00:00Z")

    citation = issue_noncompliance_action(
        permit_id, severity="MAJOR", action_type="SUSPENSION",
        cited_provision="36 CFR 251.60 - unauthorized structure",
        cure_deadline_date="2027-12-01",
    )
    assert citation["points"] == 10
    assert citation["issued_by_user_id"] == OFFICER_USER_ID

    permit = read_permit(permit_id)
    assert permit["open_noncompliance_points"] == 20, "HOP 1: the sum is recomputed from scratch"
    assert permit["compliance_status"] == "NONCOMPLIANT", "HOP 2: 20 crosses the threshold"
    assert permit["administrative_status"] == "SUSPENDED", "HOP 3: NONCOMPLIANT while ACTIVE"
    assert permit["suspension_reason_code"] == "POINTS_THRESHOLD"
    assert permit["suspension_count"] == 1
    assert permit["suspended_until_date"].startswith("2027-10-05"), (
        "30 days times one plus zero upheld MAJOR actions, from the 2027-09-05 logical date"
    )
    assert permit["authorized_client_capacity_total"] == 0, "HOP 4"

    rows, meta = list_permit_authorizations(permit_id)
    assert meta["total_count"] == 2
    assert [row["status"] for row in rows] == ["REVOKED", "REVOKED"]
    assert {row["revocation_reason_code"] for row in rows} == {"PERMIT_SUSPENDED"}
    assert sorted(row["authorized_client_capacity"] for row in rows) == [4, 8], (
        "the revoked rows keep their frozen capacity figures for the audit record"
    )

    outfitter = read_outfitter(context["outfitter"]["id"])
    assert outfitter["active_permit_count"] == 0, "HOP 5"
    assert outfitter["status"] == "SUSPENDED"
    assert outfitter["prior_permit_count"] == 1

    assert read_guide(lead["id"])["status"] == "QUALIFIED"
    assert read_guide(lead["id"])["base_client_capacity"] == 10
    assert read_guide(assistant["id"])["status"] == "QUALIFIED"
    assert read_guide(assistant["id"])["base_client_capacity"] == 4, (
        "the cascade revokes authorizations, not qualifications"
    )

    summary = read_allocation_summary(context["use_area"]["id"])
    assert summary["committed_service_days"] == 200, "SUSPENDED stays in the committed set"
    assert summary["available_service_days"] == 700


def test_the_second_threshold_breach_runs_sixty_days_behind_one_upheld_major_citation():
    """PRD §3.8: "`UPHELD` keeps the points exactly where they were — and, when the upheld action was
    `MAJOR`, lengthens every future point-threshold suspension."
    PRD §3.8: "a suspension length of 30 days multiplied by one plus the count of that permit's
    `MAJOR` actions in `UPHELD` — so a first threshold breach suspends for 30 days, and a breach
    behind one upheld major citation for 60."
    PRD §3.8: "A cured action is terminal and stops contributing points, so a cure can pull the
    permit back below a threshold; it never auto-reinstates a suspended permit."
    PRD §3.8: "Reinstatement clears `suspended_until_date` and `suspension_reason_code` to null,
    leaves `suspension_count` at its accumulated value, re-derives the compliance signals and
    `compliance_status`, and recomputes the holder's `active_permit_count` and `status`. It does
    **not** restore the guide roster the suspension revoked; the holder must authorize guides again
    from scratch."
    PRD §3.8: "`suspension_count` is a permanent tally: it is never decremented, and a single
    suspension permanently disqualifies the permit from being transferred."

    Design: Difficulty/transitive_cascade/noncompliance_points_suspension_cascade_depth_five
    """
    context = _active_permit_on_probation()
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    set_clock("2027-09-05T00:00:00Z")

    major = issue_noncompliance_action(
        permit_id, severity="MAJOR", action_type="SUSPENSION",
        cited_provision="36 CFR 251.60 - unauthorized structure",
        cure_deadline_date="2027-12-01",
    )
    first_suspension = read_permit(permit_id)
    assert first_suspension["administrative_status"] == "SUSPENDED"
    assert first_suspension["suspension_count"] == 1
    assert first_suspension["suspended_until_date"].startswith("2027-10-05")

    appeal_action(major["id"], outfitter_id)
    assert read_permit(permit_id)["open_noncompliance_points"] == 20
    upheld = decide_appeal(major["id"], "UPHELD")
    assert upheld["status"] == "UPHELD"
    kept = read_permit(permit_id)
    assert kept["open_noncompliance_points"] == 20, "UPHELD keeps the points where they were"
    assert kept["compliance_status"] == "NONCOMPLIANT"
    assert kept["administrative_status"] == "SUSPENDED"

    for action in context["actions"]:
        assert cure_action(action["id"], outfitter_id)["status"] == "CURED"
    cured = read_permit(permit_id)
    assert cured["open_noncompliance_points"] == 10
    assert cured["compliance_status"] == "PROBATION"
    assert cured["administrative_status"] == "SUSPENDED", "a cure never auto-reinstates"

    reinstated = validate_success(api_client.reinstate_permit(permit_id, OFFICER))
    assert reinstated["administrative_status"] == "ACTIVE"
    assert reinstated["compliance_status"] == "PROBATION"
    assert reinstated["suspended_until_date"] is None
    assert reinstated["suspension_reason_code"] is None
    assert reinstated["suspension_count"] == 1, "the tally is never decremented"
    assert reinstated["authorized_client_capacity_total"] == 0, (
        "the roster the suspension revoked is not restored"
    )
    assert read_outfitter(outfitter_id)["status"] == "PERMITTED"
    assert read_outfitter(outfitter_id)["active_permit_count"] == 1

    issue_noncompliance_action(
        permit_id, severity="MODERATE", action_type="SUSPENSION",
        cited_provision="operating plan clause 11 - campsite nights",
        cure_deadline_date="2027-12-01",
    )
    second_suspension = read_permit(permit_id)
    assert second_suspension["open_noncompliance_points"] == 15
    assert second_suspension["compliance_status"] == "NONCOMPLIANT"
    assert second_suspension["administrative_status"] == "SUSPENDED"
    assert second_suspension["suspension_reason_code"] == "POINTS_THRESHOLD"
    assert second_suspension["suspension_count"] == 2
    assert second_suspension["suspended_until_date"].startswith("2027-11-04"), (
        "60 days from 2027-09-05: thirty days times one plus the single upheld MAJOR citation"
    )
    assert read_outfitter(outfitter_id)["status"] == "SUSPENDED"

    rows, meta = list_noncompliance_actions(permit_id)
    assert meta["total_count"] == 4
    assert [row["status"] for row in rows] == ["CURED", "CURED", "UPHELD", "ISSUED"]


def test_the_point_window_keeps_the_action_created_exactly_1095_days_ago_and_drops_it_a_day_later():
    """PRD §3.8: "It sums the `points` of that permit's actions whose `status` is `ISSUED`,
    `APPEALED` or `UPHELD`, and whose `created_at` falls at or after the instant 1095 days before the
    current logical clock; the window boundary is inclusive, so an action created exactly 1095 days
    ago still counts, and an action created a day earlier has aged out. `CURED` and `RESCINDED`
    actions contribute nothing."
    PRD §3.8: "an appealed action **keeps contributing its points** while the appeal is pending,
    because appealing is not a stay."
    PRD §3.8: "Otherwise, if `open_noncompliance_points` is at or above **5**, or `insurance_current`
    is false, or `fee_delinquent` is true, the permit is on `PROBATION`."
    PRD §3.9: "The batch reports what it did rather than merely succeeding: `swept_at` records the
    logical instant of the run, and `certificates_expired`, `bonds_expired`, `guides_lapsed`,
    `permits_expired`, `authorizations_revoked` and `permits_suspended` count the rows each step
    moved."

    Design: Corner/calculations/noncompliance_points_count_only_open_actions_inside_the_rolling_window
    """
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides={"term_start_date": "2027-01-01", "term_end_date": "2031-12-31"},
    )
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]

    minor, moderate, major = (
        issue_noncompliance_action(
            permit_id, severity=severity, action_type=action_type,
            cited_provision=provision, cure_deadline_date="2027-03-01",
        )
        for severity, action_type, provision in (
            ("MINOR", "WARNING", "36 CFR 251.56(a) sanitation"),
            ("MODERATE", "WARNING", "36 CFR 251.56(c) stock"),
            ("MAJOR", "SUSPENSION", "36 CFR 251.60(a) resource damage"),
        )
    )
    seeded = read_permit(permit_id)
    assert seeded["open_noncompliance_points"] == 17
    assert seeded["compliance_status"] == "NONCOMPLIANT"
    assert seeded["administrative_status"] == "ISSUED", (
        "the auto-suspension propagation fires only from ACTIVE"
    )
    assert seeded["insurance_current"] is False

    cure_action(moderate["id"], outfitter_id)
    after_cure = read_permit(permit_id)
    assert after_cure["open_noncompliance_points"] == 12, "a CURED action contributes nothing"
    assert after_cure["compliance_status"] == "NONCOMPLIANT"

    appeal_action(major["id"], outfitter_id)
    assert read_permit(permit_id)["open_noncompliance_points"] == 12, (
        "APPEALED is inside the counted status set, so appealing buys no relief"
    )

    decide_appeal(major["id"], "RESCINDED")
    after_rescission = read_permit(permit_id)
    assert after_rescission["open_noncompliance_points"] == 2
    assert after_rescission["compliance_status"] == "PROBATION", (
        "below 12 and below 5, but the insurance_current branch keeps it off COMPLIANT"
    )

    set_clock("2030-01-04T00:00:00Z")
    on_the_boundary = run_sweep()
    assert on_the_boundary["swept_at"].startswith("2030-01-04")
    edge = read_permit(permit_id)
    assert edge["open_noncompliance_points"] == 2, "exactly 1095 days old and still inside"
    assert edge["compliance_status"] == "PROBATION"

    set_clock("2030-01-05T00:00:00Z")
    past_the_boundary = run_sweep()
    aged_out = read_permit(permit_id)
    assert aged_out["open_noncompliance_points"] == 0, "one day further and the action has aged out"
    assert aged_out["compliance_status"] == "PROBATION", (
        "zero points, yet the insurance branch alone still holds it on probation"
    )
    assert aged_out["administrative_status"] == "ISSUED"

    for report in (on_the_boundary, past_the_boundary):
        assert report["certificates_expired"] == 0
        assert report["bonds_expired"] == 0
        assert report["guides_lapsed"] == 0
        assert report["permits_expired"] == 0, "the term runs to 2031-12-31"
        assert report["authorizations_revoked"] == 0
        assert report["permits_suspended"] == 0

    rows, meta = list_noncompliance_actions(permit_id)
    assert meta["total_count"] == 3
    assert [row["id"] for row in rows] == [minor["id"], moderate["id"], major["id"]]
    assert [row["status"] for row in rows] == ["ISSUED", "CURED", "RESCINDED"], (
        "the rows survive; only their contribution to the sum changes"
    )


def test_the_severity_and_instrument_pair_is_judged_against_the_table_not_field_by_field():
    """PRD §3.8: "The instrument must fit the severity: `MINOR` admits `WARNING` only, `MODERATE`
    admits `WARNING` or `SUSPENSION`, and `MAJOR` admits `SUSPENSION` or `REVOCATION`; any other
    pairing is `ERR_ACTION_TYPE_NOT_ALLOWED`."
    PRD §2.5: "**Request shape** — every required field present and non-null, every enum value a
    declared member, every integer in range, every date well formed and every date pair correctly
    ordered (`ERR_INVALID_REQUEST`, 400)."
    PRD §2.5: "Checks are evaluated strictly in the following order, and the **first** violated check
    produces the response; no later check is consulted."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no `updated_at`
    refresh and no `version` increment"

    Design: Corner/validations/every_severity_action_type_pair_is_checked_against_the_matrix
    """
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides=dict(LONG_TERM),
    )
    permit_id = context["permit"]["id"]

    def _attempt(severity, action_type, provision):
        return api_client.create_noncompliance_action(
            permit_id,
            {
                "severity": severity,
                "action_type": action_type,
                "cited_provision": provision,
                "cure_deadline_date": "2027-03-01",
            },
            OFFICER,
        )

    validate_error(
        _attempt("MINOR", "SUSPENSION", "36 CFR 251.56(a)"),
        ApiErrorId.ERR_ACTION_TYPE_NOT_ALLOWED,
        422,
    )
    minor = validate_success(_attempt("MINOR", "WARNING", "36 CFR 251.56(a)"), 201)
    assert minor["points"] == 2
    assert read_permit(permit_id)["open_noncompliance_points"] == 2

    validate_error(
        _attempt("MODERATE", "REVOCATION", "36 CFR 251.56(c)"),
        ApiErrorId.ERR_ACTION_TYPE_NOT_ALLOWED,
        422,
    )
    moderate = validate_success(_attempt("MODERATE", "SUSPENSION", "36 CFR 251.56(c)"), 201)
    assert moderate["points"] == 5
    assert read_permit(permit_id)["open_noncompliance_points"] == 7

    validate_error(
        _attempt("MAJOR", "WARNING", "36 CFR 251.60(a)"),
        ApiErrorId.ERR_ACTION_TYPE_NOT_ALLOWED,
        422,
    )
    major = validate_success(_attempt("MAJOR", "SUSPENSION", "36 CFR 251.60(a)"), 201)
    assert major["points"] == 10
    assert read_permit(permit_id)["open_noncompliance_points"] == 17

    validate_error(
        _attempt("MINOR", "CITATION", "36 CFR 251.56(a)"),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    final = read_permit(permit_id)
    assert final["open_noncompliance_points"] == 17
    assert final["compliance_status"] == "NONCOMPLIANT"
    assert final["administrative_status"] == "ISSUED", (
        "the REVOCATION instrument was never accepted, so nothing closed the permit"
    )
    rows, meta = list_noncompliance_actions(permit_id)
    assert meta["total_count"] == 3, "the four refused requests wrote nothing"
    assert [row["id"] for row in rows] == [minor["id"], moderate["id"], major["id"]]
    assert [row["severity"] for row in rows] == ["MINOR", "MODERATE", "MAJOR"]
