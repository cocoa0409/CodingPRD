"""Declared transitions, and the ones that are not declared.

An application walks DRAFT to SHPO_REVIEW to NPS_REVIEW to APPROVED, an amendment
forks and joins across two agencies, and a covenant cycles through breach and cure.
Each of those machines refuses the moves its current state does not declare.
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    get_success_data,
    types,
    validate_error,
    validate_success,
)


def test_a_new_part_application_begins_in_draft_with_nothing_recorded_on_it(api):
    """Creation mints a first review round and leaves every review field empty.

    The application is created against a project that has no earlier application for
    the same part, so it supersedes nothing. It opens in DRAFT on review round one,
    with no reviewer on either side, no submission or decision stamps, both verdicts
    at NONE, both unresolved counters at zero, and a version of one.

    PRD: "A new application begins in `DRAFT` with `review_round` at 1, `shpo_reviewer_id` and `nps_reviewer_id` null, `submitted_at`, `review_window_end` and `decision_at` null, `shpo_recommendation` and `determination` both `NONE`, and both `unresolved_condition_count` and `unresolved_violation_count` at zero."
    PRD: "When no such row existed, `supersedes_application_id` stays null."
    PRD: "Operations that mint a new resource return `201 Created`."

    Design: Corner/state_machines/part_application_initial_state_is_draft
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )

    response = api.create_part_application(
        cast.developer_headers,
        **factories.part_application_payload(
            project["id"],
            1,
            project["version"],
            narrative="Evaluation of significance for the 1912 Elm Mill.",
        ),
    )

    application = validate_success(response, 201)
    types.assert_is_part_application(application)
    assertions.assert_fields(
        application,
        "new part application",
        status="DRAFT",
        review_round=1,
        shpo_reviewer_id=None,
        nps_reviewer_id=None,
        submitted_at=None,
        review_window_end=None,
        decision_at=None,
        shpo_recommendation="NONE",
        determination="NONE",
        supersedes_application_id=None,
        unresolved_condition_count=0,
        unresolved_violation_count=0,
        version=1,
    )


def test_submission_writes_the_reviewer_and_derives_the_thirty_day_window(api):
    """DRAFT to SHPO_REVIEW records who holds it and until when.

    The developer names the state office reviewer at submission, and that id is
    written onto the application. The submission stamp comes from the logical clock
    pinned at 2026-09-01 and the window end is thirty days later, on 2026-10-01. The
    review round is untouched and the version has advanced once.

    PRD: "Submission moves an application from `DRAFT` to `SHPO_REVIEW` and is the point at which the state preservation office reviewer is chosen: the developer supplies `shpo_reviewer_id`, which is written onto the application."
    PRD: "Submission stamps `submitted_at` from the logical clock and derives `review_window_end` as that instant advanced by thirty days, which together bound the reviewer's occupation interval as a closed date interval."
    PRD: "Submission increments the application's `version` by one."

    Design: Corner/state_machines/part_application_submit_records_reviewer_and_review_window
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    application = fixtures.create_part_application(api, cast, project["id"], 1)

    submitted = validate_success(
        api.submit_part_application(
            application["id"],
            cast.developer_headers,
            shpo_reviewer_id=cast.shpo_reviewer_id,
        )
    )

    assertions.assert_fields(
        submitted,
        "submitted application",
        status="SHPO_REVIEW",
        shpo_reviewer_id=cast.shpo_reviewer_id,
        review_round=1,
        version=2,
    )
    assert submitted["submitted_at"].startswith("2026-09-01T00:00:00"), (
        "submitted_at is stamped from the pinned logical clock"
    )
    assert submitted["review_window_end"].startswith("2026-10-01T00:00:00"), (
        "the window ends thirty days after submission"
    )


def test_a_recommendation_on_a_never_submitted_application_is_refused(api):
    """The recommendation is declared only from SHPO_REVIEW, so DRAFT refuses it.

    The application has never been submitted, so no reviewer holds it and the
    recommendation transition is not declared from its current state. The refusal
    leaves the application in DRAFT with its verdict still NONE and its version still
    at the value creation gave it.

    PRD: "The requested transition is declared from the target's current state, else that entity's invalid-state error (`ERR_PART_APPLICATION_INVALID_STATE`, `ERR_AMENDMENT_INVALID_STATE`, `ERR_COVENANT_INVALID_STATE`, `ERR_PROJECT_INVALID_STATE`, all 409), together with the other state-shaped preconditions: `ERR_CREDIT_CLAIM_ALREADY_FILED`, `ERR_PROJECT_NOT_CERTIFIED`, `ERR_PROJECT_NOT_PLACED_IN_SERVICE`, `ERR_COST_ITEM_LOCKED` (409) and `ERR_ELECTION_WINDOW_CLOSED` (422)."
    PRD: "The office holding the application recommends first. A `ShpoReviewer` whose `X-User-ID` equals the application's `shpo_reviewer_id` and whose `credential_status` is still `ACTIVE` records a `recommendation` of either `RECOMMEND_APPROVAL` or `RECOMMEND_DENIAL` into `shpo_recommendation`, optionally attaching a `review_note`, and the application advances `SHPO_REVIEW → NPS_REVIEW`."

    Design: Corner/state_machines/shpo_recommend_from_draft_status_rejected
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    application = fixtures.create_part_application(api, cast, project["id"], 1)

    response = api.shpo_recommend(
        application["id"], cast.shpo_headers, recommendation="RECOMMEND_APPROVAL"
    )

    validate_error(response, ApiErrorId.PART_APPLICATION_INVALID_STATE.value, 409)
    stored = get_success_data(
        api.get_part_application(application["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        stored,
        "application after the refused recommendation",
        status="DRAFT",
        shpo_recommendation="NONE",
        version=1,
    )


def test_a_second_determination_on_an_approved_application_is_refused(api):
    """APPROVED is closed, so a later DENIED determination cannot overwrite it.

    The application was carried to APPROVED by a recommendation and a determination
    from two distinct reviewers. A second determination on the same row is an
    already-advanced replay and is refused, leaving the approved verdict, the decision
    stamp, the certified building and the advanced project exactly as the approval
    left them.

    PRD: "This band also catches idempotent replays — a second request for the same action on an already-advanced row."
    PRD: "The binding determination is issued by an `NpsReviewer` on an application in `NPS_REVIEW`."
    PRD: "For a Part 1 application, the first hop sets the property's `evaluation_status` to `CERTIFIED_HISTORIC` and stamps its `certified_at` from the logical clock, bumping the property's `version`."

    Design: Corner/state_machines/nps_determination_twice_rejected_as_invalid_state
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    approved = fixtures.walk_part_to_approved(api, cast, project["id"], 1)

    response = api.nps_determination(
        approved["id"], cast.nps_headers, determination="DENIED"
    )

    validate_error(response, ApiErrorId.PART_APPLICATION_INVALID_STATE.value, 409)
    stored = get_success_data(
        api.get_part_application(approved["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        stored,
        "application after the refused replay",
        status="APPROVED",
        determination="APPROVED",
    )
    assert stored["decision_at"].startswith("2026-09-01T00:00:00"), (
        "the decision stamp is the one the approval wrote"
    )
    assertions.assert_project_state(
        fixtures.read_project(api, cast, project["id"]),
        certification_status="PART1_CERTIFIED",
    )
    stored_property = get_success_data(
        api.get_property(cast.property_id, cast.developer_headers)
    )
    assertions.assert_fields(
        stored_property, "certified property", evaluation_status="CERTIFIED_HISTORIC"
    )


def test_a_superseded_application_can_no_longer_be_submitted(api):
    """Re-applying for the same part closes the old row against submission.

    A second Part 1 application on the same project drives the first to SUPERSEDED
    and records the superseded row's id on the new one. Submitting the superseded row
    is refused, and it keeps no reviewer and no submission stamp, while the live row
    waits in DRAFT.

    PRD: "When an application already exists for the same project and the same `part_number` and its status is any non-terminal value — `DRAFT`, `SHPO_REVIEW`, `NPS_REVIEW`, `CONDITIONAL`, or `REVISION_REQUIRED` — that row transitions to `SUPERSEDED`, its `version` increments, its reviewer occupation interval is released so it no longer counts against that reviewer's capacity, and the new row records the superseded row's `id` in `supersedes_application_id`."
    PRD: "`APPROVED` and `SUPERSEDED` rows are never superseded: once a part is `APPROVED` it is closed, and a further application for it is refused with `ERR_PART_ALREADY_CERTIFIED`."

    Design: Corner/state_machines/superseded_draft_part_application_rejects_submit
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    first = fixtures.create_part_application(
        api, cast, project["id"], 1, narrative="First evaluation of significance."
    )
    second = fixtures.create_part_application(
        api, cast, project["id"], 1, narrative="Revised evaluation of significance."
    )

    response = api.submit_part_application(
        first["id"], cast.developer_headers, shpo_reviewer_id=cast.shpo_reviewer_id
    )

    validate_error(response, ApiErrorId.PART_APPLICATION_INVALID_STATE.value, 409)
    stored_first = get_success_data(
        api.get_part_application(first["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        stored_first,
        "superseded application",
        status="SUPERSEDED",
        shpo_reviewer_id=None,
        submitted_at=None,
    )
    assertions.assert_fields(
        second,
        "replacement application",
        status="DRAFT",
        supersedes_application_id=first["id"],
    )


def test_an_approval_over_an_unresolved_violation_finding_is_refused(api):
    """A VIOLATION can never be waived, so approval is blocked while it stands.

    The federal reviewer raised a VIOLATION finding against Standard 9 on an
    application in NPS_REVIEW, which put the unresolved violation counter at one. An
    APPROVED determination requires that counter to be zero, so it is refused. The
    application stays in NPS_REVIEW with no verdict, the finding stays UNRESOLVED, and
    neither the project nor the building has moved.

    PRD: "It requires, after the waivers have been applied, that `unresolved_violation_count` be zero — otherwise `ERR_PRESERVATION_STANDARD_VIOLATION` — and that `unresolved_condition_count` also be zero; an `APPROVED` determination attempted while unresolved conditions remain is refused with `ERR_PART_APPLICATION_INVALID_STATE`, since `CONDITIONAL` is the declared outcome in that situation."
    PRD: "A new finding starts with `resolution_state` of `UNRESOLVED`."
    PRD: "A `CONDITION` finding raises the application's `unresolved_condition_count` by one and a `VIOLATION` finding raises its `unresolved_violation_count` by one; either way the application's `version` increments."

    Design: Corner/state_machines/nps_approval_with_unresolved_violation_finding_rejected
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    application = fixtures.create_part_application(api, cast, project["id"], 1)
    fixtures.submit_part_application(api, cast, application["id"])
    fixtures.shpo_recommend(api, cast, application["id"])
    finding = fixtures.add_finding(
        api,
        cast,
        application["id"],
        headers=cast.nps_headers,
        standard_number=9,
        severity="VIOLATION",
        description="The proposed rear addition destroys historic fabric.",
    )

    response = api.nps_determination(
        application["id"], cast.nps_headers, determination="APPROVED"
    )

    validate_error(response, ApiErrorId.PRESERVATION_STANDARD_VIOLATION.value, 422)
    stored = get_success_data(
        api.get_part_application(application["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        stored,
        "application after the blocked approval",
        status="NPS_REVIEW",
        determination="NONE",
        decision_at=None,
        unresolved_violation_count=1,
    )
    stored_finding = validate_success(api.get_finding(finding["id"], cast.nps_headers))
    assertions.assert_fields(
        stored_finding, "violation finding", resolution_state="UNRESOLVED"
    )
    assertions.assert_project_state(
        fixtures.read_project(api, cast, project["id"]),
        certification_status="PRE_CERTIFICATION",
    )
    stored_property = get_success_data(
        api.get_property(cast.property_id, cast.developer_headers)
    )
    assertions.assert_fields(
        stored_property, "property", evaluation_status="UNEVALUATED"
    )


def test_part_one_approval_certifies_the_building_and_advances_the_project(api):
    """One determination writes the application, the property and the project.

    With a positive recommendation and no findings, the federal determination approves
    the application, stamps the acting reviewer and the decision instant, certifies the
    building with a certification timestamp from the same clock, and advances the
    project's certification dimension one step. The compliance dimension is untouched,
    because nothing has been placed in service.

    PRD: "For a Part 1 application, the first hop sets the property's `evaluation_status` to `CERTIFIED_HISTORIC` and stamps its `certified_at` from the logical clock, bumping the property's `version`."
    PRD: "The second hop advances the project's certification dimension according to the part number: `PRE_CERTIFICATION → PART1_CERTIFIED` for Part 1, `PART1_CERTIFIED → PART2_APPROVED` for Part 2, and `PART2_APPROVED → PART3_CERTIFIED` for Part 3, bumping the project's `version`."
    PRD: "All three branches stamp `determination`, set `nps_reviewer_id` to the caller's `X-User-ID`, set `decision_at` from the logical clock, and increment the application's `version` by one."

    Design: Corner/state_machines/part1_approval_certifies_property_and_bubbles_project_to_part1_certified
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    application = fixtures.create_part_application(api, cast, project["id"], 1)
    fixtures.submit_part_application(api, cast, application["id"])
    fixtures.shpo_recommend(api, cast, application["id"])

    approved = validate_success(
        api.nps_determination(
            application["id"], cast.nps_headers, determination="APPROVED"
        )
    )

    assertions.assert_fields(
        approved,
        "approved application",
        status="APPROVED",
        determination="APPROVED",
        nps_reviewer_id=cast.nps_reviewer_id,
    )
    assert approved["decision_at"].startswith("2026-09-01T00:00:00"), (
        "the decision instant comes from the logical clock"
    )
    stored_property = get_success_data(
        api.get_property(cast.property_id, cast.developer_headers)
    )
    assertions.assert_fields(
        stored_property, "certified property", evaluation_status="CERTIFIED_HISTORIC"
    )
    assert stored_property["certified_at"].startswith("2026-09-01T00:00:00"), (
        "certification is stamped from the same clock"
    )
    stored_project = fixtures.read_project(api, cast, project["id"])
    assertions.assert_project_state(
        stored_project,
        certification_status="PART1_CERTIFIED",
        compliance_status="NOT_MONITORED",
    )
    assertions.assert_fields(
        stored_project, "project", placed_in_service_date=None
    )


def test_a_state_office_concurrence_alone_holds_a_two_agency_amendment(api):
    """The fork waits for the federal office, while a pure scope change joins at once.

    Two amendments sit against the same CONDITIONAL Part 2 application. The ADDITION
    that addresses the outstanding condition needs both agencies, so the state office
    CONCUR only advances it to SHPO_CONCURRED with the federal verdict still NONE and
    the finding still unresolved. The WINDOW_REPLACEMENT with a 100000-cent delta
    addresses nothing and needs only the state office, so the same CONCUR takes it
    straight to CONCURRED without clearing anything. The application is therefore still
    parked with one unresolved condition and the project has not advanced.

    PRD: "When `requires_nps_concurrence` is true, that same `CONCUR` from an `ACTIVE` `SHPO` reviewer only advances the amendment `SUBMITTED → SHPO_CONCURRED` and sets `shpo_decision` to `CONCUR`."
    PRD: "When `requires_nps_concurrence` is false, a `CONCUR` from an `ACTIVE` `SHPO` reviewer joins immediately: the amendment moves `SUBMITTED → CONCURRED` and `shpo_decision` becomes `CONCUR`."
    PRD: "An amendment may also be aimed at an outstanding finding by supplying `addresses_finding_id`; omitting it makes the amendment a pure scope change that clears nothing."

    Design: Corner/state_machines/amendment_shpo_only_concurrence_holds_at_shpo_concurred
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    fixtures.walk_part_to_approved(api, cast, project["id"], 1)
    part2 = fixtures.create_part_application(api, cast, project["id"], 2)
    fixtures.submit_part_application(api, cast, part2["id"])
    fixtures.shpo_recommend(api, cast, part2["id"])
    condition = fixtures.add_finding(
        api,
        cast,
        part2["id"],
        headers=cast.nps_headers,
        standard_number=2,
        severity="CONDITION",
        description="The storefront alteration must retain the cast-iron piers.",
    )
    fixtures.nps_determine(api, cast, part2["id"], determination="CONDITIONAL")
    two_agency = validate_success(
        api.create_amendment(
            cast.developer_headers,
            **factories.amendment_payload(
                project["id"],
                part2["id"],
                scope_category="ADDITION",
                change_description="A rear stair enclosure is added to the scope.",
                cost_delta_cents=100_000,
                addresses_finding_id=condition["id"],
            ),
        ),
        201,
    )
    state_office_only = validate_success(
        api.create_amendment(
            cast.developer_headers,
            **factories.amendment_payload(
                project["id"],
                part2["id"],
                scope_category="WINDOW_REPLACEMENT",
                change_description="Two sash units are repaired rather than replaced.",
                cost_delta_cents=100_000,
            ),
        ),
        201,
    )
    validate_success(api.submit_amendment(two_agency["id"], cast.developer_headers))
    validate_success(
        api.submit_amendment(state_office_only["id"], cast.developer_headers)
    )

    held = validate_success(
        api.concur_amendment(two_agency["id"], cast.shpo_headers, decision="CONCUR")
    )
    joined = validate_success(
        api.concur_amendment(
            state_office_only["id"], cast.shpo_headers, decision="CONCUR"
        )
    )

    assertions.assert_fields(
        held,
        "amendment awaiting the federal office",
        requires_nps_concurrence=True,
        status="SHPO_CONCURRED",
        shpo_decision="CONCUR",
        nps_decision="NONE",
    )
    assertions.assert_fields(
        joined,
        "pure scope change",
        requires_nps_concurrence=False,
        status="CONCURRED",
        shpo_decision="CONCUR",
        nps_decision="NONE",
    )
    stored_finding = validate_success(
        api.get_finding(condition["id"], cast.nps_headers)
    )
    assertions.assert_fields(
        stored_finding, "addressed condition", resolution_state="UNRESOLVED"
    )
    stored_application = get_success_data(
        api.get_part_application(part2["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        stored_application,
        "parked part 2",
        status="CONDITIONAL",
        unresolved_condition_count=1,
    )
    assertions.assert_project_state(
        fixtures.read_project(api, cast, project["id"]),
        certification_status="PART1_CERTIFIED",
    )


def test_a_satisfied_attestation_cures_a_breached_covenant_within_the_deadline(api):
    """EXCEPTION then SATISFIED walks the covenant BREACHED to CURED.

    The covenant's monitoring window runs 2029-01-15 to 2029-01-31, and an EXCEPTION
    attestation for that period breaches it, setting the cure deadline ninety days
    after the window end, on 2029-05-01. A SATISFIED attestation for the period ending
    2029-04-30 arrives on the deadline itself, so the cure is accepted: the covenant is
    CURED on its second attestation with one exception recorded, and because no other
    covenant is breached and nothing is outstanding, the project's compliance dimension
    returns to monitoring while its certification dimension stays where Part 2 left it.

    PRD: "From `PENDING_ATTESTATION`, `COMPLIANT`, or `CURED`, the covenant moves to `BREACHED`; `exception_count` rises by one alongside `attestation_count`, and `cure_deadline_date` is set to `window_end_date` advanced by ninety days."
    PRD: "A `SATISFIED` attestation on a `BREACHED` covenant moves it `BREACHED → CURED`, but only when the attested `period_end_date` falls on or before `cure_deadline_date`; a cure attestation arriving after that deadline is refused with `ERR_COVENANT_INVALID_STATE`."
    PRD: "A successful cure re-scores every `ADMITTED` interest under the `IN_SERVICE` variant, and when no other covenant of the project is `BREACHED` and `recapture_balance_cents` is zero, it returns the project's compliance dimension `CURE_PENDING → IN_SERVICE_MONITORING` and settles the outstanding recapture events, incrementing the project's `version`."

    Design: Corner/state_machines/covenant_exception_then_satisfied_cycles_breached_to_cured
    """
    scenario = fixtures.part2_approved_project(
        api, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    fixtures.declare_in_service(
        api, cast, project_id, placed_in_service_date="2029-01-15"
    )
    covenant = fixtures.create_covenant(
        api,
        cast,
        project_id,
        covenant_type="USE_RESTRICTION",
        monitoring_frequency="ANNUAL",
        window_start_date="2029-01-15",
        window_end_date="2029-01-31",
    )
    breached = fixtures.attest_covenant(
        api, cast, covenant["id"], "2029-01-31", "EXCEPTION"
    )
    assertions.assert_fields(
        breached,
        "breached covenant",
        status="BREACHED",
        attestation_count=1,
        exception_count=1,
        cure_deadline_date="2029-05-01",
    )
    assertions.assert_project_state(
        fixtures.read_project(api, cast, project_id),
        compliance_status="CURE_PENDING",
    )
    fixtures.set_clock(api, "2029-05-01T00:00:00Z")

    cured = fixtures.attest_covenant(
        api, cast, covenant["id"], "2029-04-30", "SATISFIED"
    )

    assertions.assert_fields(
        cured,
        "cured covenant",
        status="CURED",
        attestation_count=2,
        exception_count=1,
        last_attested_period_end="2029-04-30",
        cure_deadline_date="2029-05-01",
    )
    stored_project = fixtures.read_project(api, cast, project_id)
    assertions.assert_project_state(
        stored_project,
        certification_status="PART2_APPROVED",
        compliance_status="IN_SERVICE_MONITORING",
    )
    assertions.assert_ledger(stored_project, recapture_balance_cents=0)
