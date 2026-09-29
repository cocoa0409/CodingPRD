"""Validation breadth: the last accepted value on a boundary and the first
rejected one, a conditional field requirement, a scope ceiling, a uniqueness
constraint, a cross-aggregate reference and a date that must not be in the past."""

from test_helpers import (
    LEAD,
    LIAISON,
    TESTER,
    assessment_payload,
    complaint_payload,
    complaint_triage_payload,
    commit_issue_payload,
    create_component,
    create_criterion,
    create_environment,
    create_product,
    create_release_train,
    create_standard,
    intake_complaint,
    link_issue_payload,
    log_issue,
    read_complaint,
    read_component,
    read_environment,
    read_known_issue,
    read_release_train,
    run_payload,
    standard_payload,
    triage_complaint,
    triage_issue,
    validate_error,
    validate_paginated,
    validate_success,
)

# The train's window runs 2026-09-05..2026-09-27 with a two-day freeze tail, so
# its usable window ends on 2026-09-25.
TRAIN_WINDOW = ("2026-09-05", "2026-09-27")
FREEZE_DAYS = 2
LAST_USABLE_DAY = "2026-09-25"
FIRST_FROZEN_DAY = "2026-09-26"
ISSUE_EFFORT_POINTS = 3

APPLICABLE_CRITERIA = 40
OVER_SCOPE_CRITERIA = 41

RUN_WINDOW = ("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")

# The logical clock starts at 2026-08-01, so this date is a week in the past.
PAST_NEEDED_BY_DATE = "2026-07-25"


def build_inventory_with_a_train(target_remediation_date):
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    criterion = create_criterion(
        standard["id"],
        criterion_number="1.1.1",
        title="Non-text Content",
        level="A",
        disability_categories=["VISION"],
        applies_to_surfaces=["WEB"],
    )
    product = create_product(
        standard["id"],
        name="Insight Portal",
        version_label="7.0",
        target_level="AA",
        surface_type="WEB",
    )
    component = create_component(
        product["id"],
        name="Web UI",
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=APPLICABLE_CRITERIA,
        user_reach_pct=60,
    )
    train = create_release_train(
        name="Train 2026.09",
        window_start=TRAIN_WINDOW[0],
        window_end=TRAIN_WINDOW[1],
        freeze_days=FREEZE_DAYS,
        effort_capacity_points=10,
        remediation_budget_cents=100000,
    )
    issue = log_issue(
        product["id"],
        component["id"],
        criterion["id"],
        severity="SERIOUS",
        effort_points=ISSUE_EFFORT_POINTS,
        target_remediation_date=target_remediation_date,
        publish_intent="INCLUDED",
        summary="Media library thumbnails expose no accessible name",
    )
    triage_issue(issue["id"], triage_note="Confirmed on NVDA and JAWS")
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": component,
        "train": train,
        "issue": issue,
    }


def build_two_products_on_one_standard():
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    criterion = create_criterion(
        standard["id"],
        criterion_number="1.1.1",
        title="Non-text Content",
        level="A",
        disability_categories=["VISION"],
        applies_to_surfaces=["WEB"],
    )
    product_a = create_product(
        standard["id"],
        name="Insight Portal",
        version_label="7.0",
        target_level="AA",
        surface_type="WEB",
    )
    component_a = create_component(
        product_a["id"],
        name="Web UI",
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=APPLICABLE_CRITERIA,
        user_reach_pct=60,
    )
    product_b = create_product(
        standard["id"],
        name="Insight Mobile",
        version_label="3.1",
        target_level="AA",
        surface_type="WEB",
    )
    component_b = create_component(
        product_b["id"],
        name="Mobile Shell",
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=30,
        user_reach_pct=40,
    )
    foreign_issue = log_issue(
        product_b["id"],
        component_b["id"],
        criterion["id"],
        severity="SERIOUS",
        effort_points=2,
        target_remediation_date="2026-12-01",
        publish_intent="INCLUDED",
        summary="Mobile shell traps focus in the navigation drawer",
    )
    complaint = intake_complaint(
        product_a["id"],
        component_id=component_a["id"],
        criterion_id=criterion["id"],
        channel="EMAIL",
        description="Images in the report viewer have no alternative text",
        disability_category="VISION",
    )
    triage_complaint(complaint["id"], route="REMEDIATION")
    return {
        "standard": standard,
        "criterion": criterion,
        "product_a": product_a,
        "component_a": component_a,
        "product_b": product_b,
        "component_b": component_b,
        "foreign_issue": foreign_issue,
        "complaint": complaint,
    }


class TestUsableTrainWindowBoundary:
    """The last usable day is inside; the first frozen day is outside."""

    def test_a_target_on_the_last_usable_day_is_committed(self, api):
        """PRD §3.9: "The issue's `target_remediation_date` must land inside the
        train's **usable** window, which begins at `window_start` and ends at
        `window_end` minus the train's `freeze_days`, both endpoints included — a
        target date on the last usable day is accepted, a target date one day later
        falls inside the code freeze and is rejected with
        `ERR_TARGET_DATE_OUTSIDE_TRAIN_WINDOW`."
        PRD §3.9: "On success the issue moves `TRIAGED → COMMITTED`, its
        `release_train_id` is recorded, the train's `committed_effort_points` rises
        by the issue's `effort_points`, and the product's `publication_posture` is
        rebuilt."

        Design: Corner/validations/corner_commit_target_date_on_last_usable_day_succeeds
        """
        ctx = build_inventory_with_a_train(LAST_USABLE_DAY)

        committed = validate_success(
            api.commit_issue(
                ctx["issue"]["id"], commit_issue_payload(ctx["train"]["id"]), LEAD
            )
        )

        assert committed["state"] == "COMMITTED", (
            f"2026-09-25 is the last day before the freeze tail, got {committed['state']}"
        )
        assert committed["release_train_id"] == ctx["train"]["id"]
        train = read_release_train(ctx["train"]["id"])
        assert train["committed_effort_points"] == ISSUE_EFFORT_POINTS, (
            "the train takes on the issue's three points, got "
            f"{train['committed_effort_points']}"
        )

    def test_a_target_one_day_later_falls_inside_the_freeze_tail(self, api):
        """PRD §3.9: "The issue's `target_remediation_date` must land inside the
        train's **usable** window, which begins at `window_start` and ends at
        `window_end` minus the train's `freeze_days`, both endpoints included — a
        target date on the last usable day is accepted, a target date one day later
        falls inside the code freeze and is rejected with
        `ERR_TARGET_DATE_OUTSIDE_TRAIN_WINDOW`."
        PRD §3.9: "Thereafter `committed_effort_points` always equals the sum of
        `effort_points` over the train's issues in states `COMMITTED` and
        `PUBLISHED_COMMITTED`, and `unallocated_cents` always equals
        `remediation_budget_cents` minus the sum of `funded_cents` over the train's
        issues."

        Design: Corner/validations/corner_commit_target_date_inside_freeze_window_rejected
        """
        ctx = build_inventory_with_a_train(FIRST_FROZEN_DAY)

        validate_error(
            api.commit_issue(
                ctx["issue"]["id"], commit_issue_payload(ctx["train"]["id"]), LEAD
            ),
            "ERR_TARGET_DATE_OUTSIDE_TRAIN_WINDOW",
            422,
        )

        issue = read_known_issue(ctx["issue"]["id"])
        assert issue["state"] == "TRIAGED", (
            f"the refused commitment transitions nothing, got {issue['state']}"
        )
        assert issue["release_train_id"] is None
        train = read_release_train(ctx["train"]["id"])
        assert train["committed_effort_points"] == 0, (
            "no issue reached COMMITTED, so the train carries no points, got "
            f"{train['committed_effort_points']}"
        )


class TestConditionallyRequiredFields:
    """A qualified claim must explain itself; unqualified support need not."""

    def test_partial_support_without_remarks_is_rejected(self, api):
        """PRD §3.5: "A `support_level` of `PARTIALLY_SUPPORTS`,
        `DOES_NOT_SUPPORT` or `NOT_APPLICABLE` requires `remarks` of at least 10
        characters; omitting them, or supplying fewer than 10 characters, is
        rejected with `ERR_REMARKS_REQUIRED`."
        PRD §3.5: "Only a `support_level` of `SUPPORTS` may stand without
        explanation."
        PRD §2.9: "Counters, coverage percentages, indices, postures, funding
        states and readiness flags are never supplied by clients and never accepted
        in a request body; they are recomputed by the server from their inputs
        whenever an operation changes one of those inputs."

        Design: Corner/validations/corner_partial_support_without_remarks_rejected
        """
        ctx = build_two_products_on_one_standard()
        component_version = read_component(ctx["component_a"]["id"])["version"]

        validate_error(
            api.create_assessment(
                assessment_payload(
                    ctx["component_a"]["id"],
                    ctx["criterion"]["id"],
                    component_version,
                    support_level="PARTIALLY_SUPPORTS",
                ),
                TESTER,
            ),
            "ERR_REMARKS_REQUIRED",
            422,
        )

        _rows, meta = validate_paginated(
            api.list_assessments(TESTER, {"component_id": ctx["component_a"]["id"]})
        )
        assert meta["total_count"] == 0, (
            f"the rejected authoring wrote no row, got {meta['total_count']}"
        )
        assert read_component(ctx["component_a"]["id"])["version"] == component_version, (
            "the rejected write bumped nothing on the component"
        )


class TestScopeCeilings:
    """A run cannot exercise more criteria than the component declares."""

    def test_a_run_exercising_more_criteria_than_the_scope_is_refused(self, api):
        """PRD §3.3: "The `criteria_exercised` figure must not exceed the
        component's declared `applicable_criteria_count`, because a run cannot
        exercise more criteria than the component has in scope; exceeding it is
        `ERR_EXERCISED_EXCEEDS_SCOPE`."
        PRD §3.3: "Scheduling the first run for a component is what starts its
        testing dimension: the component moves `PLANNED → IN_TESTING`, provided its
        declared `assessment_scope` is not `EXCLUDED` — a component declared out of
        assessment depth stays at `PLANNED` no matter how many runs are booked
        against it."
        PRD §3.3: "A bench also reports a derived `scheduled_run_count`, being the
        number of runs on it whose `status` is either `SCHEDULED` or `COMPLETED`."

        Design: Corner/validations/corner_run_exercising_more_criteria_than_scope_rejected
        """
        ctx = build_inventory_with_a_train(LAST_USABLE_DAY)
        bench = create_environment(
            name="NVDA Bench 1", at_profile="SCREEN_READER", reconfiguration_buffer_minutes=30
        )

        validate_error(
            api.create_run(
                run_payload(
                    ctx["component"]["id"],
                    bench["id"],
                    method="MANUAL",
                    at_profile="SCREEN_READER",
                    scheduled_start=RUN_WINDOW[0],
                    scheduled_end=RUN_WINDOW[1],
                    criteria_exercised=OVER_SCOPE_CRITERIA,
                    disability_categories_validated=["VISION"],
                ),
                TESTER,
            ),
            "ERR_EXERCISED_EXCEEDS_SCOPE",
            422,
        )

        component = read_component(ctx["component"]["id"])
        assert component["assessment_state"] == "PLANNED", (
            "no booking took hold, so testing never started, got "
            f"{component['assessment_state']}"
        )
        assert read_environment(bench["id"])["scheduled_run_count"] == 0, (
            "the refused booking is not counted against the bench"
        )


class TestUniquenessConstraints:
    """A standard code identifies a published document, so it is global."""

    def test_reusing_a_standard_code_under_a_different_title_is_refused(self, api):
        """PRD §3.1: "Because a standard code identifies a published document,
        registering a second standard with an already-registered `code` is rejected
        with `ERR_DUPLICATE_STANDARD_CODE`."
        PRD §2.10: "A standard's `code` is globally unique across standards; a
        criterion's `criterion_number` is unique within its owning standard; a
        component's `name` is unique within its owning product; a test
        environment's `name` and a release train's `name` are each globally
        unique."
        PRD §2.10: "Violations surface as `ERR_DUPLICATE_STANDARD_CODE`,
        `ERR_DUPLICATE_CRITERION_NUMBER`, `ERR_DUPLICATE_COMPONENT_NAME`,
        `ERR_DUPLICATE_ENVIRONMENT_NAME` and `ERR_DUPLICATE_TRAIN_NAME`
        respectively, all with HTTP 409."

        Design: Corner/validations/corner_duplicate_standard_code_rejected
        """
        incumbent = create_standard(
            code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
        )

        validate_error(
            api.create_standard(
                standard_payload(
                    code="WCAG_2_2",
                    title="WCAG 2.2 second intake",
                    surface_scope="SOFTWARE",
                    max_target_level="AA",
                ),
                LEAD,
            ),
            "ERR_DUPLICATE_STANDARD_CODE",
            409,
        )

        stored = validate_success(api.get_standard(incumbent["id"], LEAD))
        assert stored["surface_scope"] == "WEB", (
            "uniqueness is on the code alone, and the incumbent row is untouched, got "
            f"{stored['surface_scope']}"
        )
        assert stored["max_target_level"] == "AAA"
        assert stored["title"] == "WCAG 2.2"


class TestCrossAggregateReferences:
    """An issue that exists but belongs elsewhere is a 422, not a 404."""

    def test_linking_a_complaint_to_another_products_issue_is_refused(self, api):
        """PRD §3.11: "The `REMEDIATION` branch continues by linking the complaint
        to a known issue, naming the `known_issue_id`."
        PRD §3.11: "Linking requires the complaint to be `TRIAGED` — otherwise
        `ERR_COMPLAINT_NOT_TRIAGED` — requires its `route` to be `REMEDIATION`,
        since an accommodation request has no defect to link and the attempt is
        `ERR_COMPLAINT_ROUTE_MISMATCH`, and requires the named issue to belong to
        the same product as the complaint, or the request is
        `ERR_CROSS_PRODUCT_REFERENCE`."
        PRD §3.11: "On success the complaint moves `TRIAGED → LINKED`, its
        `linked_issue_id` is recorded, the issue's `linked_complaint_count` rises by
        1, and the issue's `risk_score` is recomputed under whichever `risk_variant`
        it currently carries — which is how customer pressure feeds back into
        prioritization, since the `BOARD_REVIEW` variant amplifies by the complaint
        count while the `INTAKE_ESTIMATE` variant ignores it."

        Design: Corner/validations/corner_link_issue_from_another_product_rejected
        """
        ctx = build_two_products_on_one_standard()

        validate_error(
            api.link_issue(
                ctx["complaint"]["id"],
                link_issue_payload(ctx["foreign_issue"]["id"]),
                LEAD,
            ),
            "ERR_CROSS_PRODUCT_REFERENCE",
            422,
        )

        complaint = read_complaint(ctx["complaint"]["id"])
        assert complaint["state"] == "TRIAGED", (
            f"the refused link transitions nothing, got {complaint['state']}"
        )
        assert complaint["linked_issue_id"] is None
        assert read_known_issue(ctx["foreign_issue"]["id"])["linked_complaint_count"] == 0, (
            "the foreign issue feels no customer pressure from another product's complaint"
        )


class TestDatesThatMustNotBeInThePast:
    """An accommodation cannot be needed before the request is even triaged."""

    def test_an_accommodation_needed_by_a_past_date_is_refused(self, api):
        """PRD §3.11: "That date must not be in the past — it must fall on or after
        the logical clock's current date — or the request is rejected with
        `ERR_ACCOMMODATION_DATE_IN_PAST`."
        PRD §3.11: "A new complaint is in state `NEW` with no `route` yet assigned,
        and no `linked_issue_id`, `requested_accommodation`, `needed_by_date`,
        `accommodation_fulfilled_at`, `closure_outcome` or `closed_at`."
        PRD §2.4: "The clock begins at `2026-08-01T00:00:00Z` and an
        `AccessibilityLead` may move it to any instant supplied as `to_iso8601`."

        Design: Corner/validations/corner_accommodation_needed_by_date_in_past_rejected
        """
        ctx = build_two_products_on_one_standard()
        fresh = validate_success(
            api.create_complaint(
                complaint_payload(
                    ctx["product_a"]["id"],
                    component_id=ctx["component_a"]["id"],
                    channel="PHONE",
                    description="I need the report exported in large print",
                    disability_category="VISION",
                ),
                LIAISON,
            ),
            201,
        )

        validate_error(
            api.triage_complaint(
                fresh["id"],
                complaint_triage_payload(
                    route="ACCOMMODATION",
                    requested_accommodation="Large-print export of the conformance report",
                    needed_by_date=PAST_NEEDED_BY_DATE,
                ),
                LEAD,
            ),
            "ERR_ACCOMMODATION_DATE_IN_PAST",
            422,
        )

        complaint = read_complaint(fresh["id"])
        assert complaint["state"] == "NEW", (
            f"the refused triage leaves the complaint unrouted, got {complaint['state']}"
        )
        assert complaint["route"] is None
        assert complaint["needed_by_date"] is None, (
            f"nothing from the refused body was persisted, got {complaint['needed_by_date']}"
        )
