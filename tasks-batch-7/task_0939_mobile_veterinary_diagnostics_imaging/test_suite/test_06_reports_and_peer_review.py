"""The reporting chain, supersession, retraction and the peer-review axis."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_same_instant,
    draft_and_publish_report,
    draft_report,
    make_clinic_user_headers,
    make_specialist_headers,
    new_specialist,
    offer_and_accept_read,
    publish_report,
    set_clock,
    setup_telerad_scene,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def _study_with_published_preliminary_and_drafted_final(api):
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(clinic_name="Report Vet", address_zone="ZP",
                                technician_name="Hub QC Four", image_count=20)
    specialist = new_specialist("Dr Rowe", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    study = scene["studies"][0]
    assignment = offer_and_accept_read(study["id"], specialist["id"])
    preliminary = draft_report(study["id"], specialist["id"], kind="PRELIMINARY",
                              findings="possible renal cysts")
    published_preliminary = publish_report(preliminary["id"], specialist["id"])
    final = draft_report(study["id"], specialist["id"], kind="FINAL",
                         findings="bilateral renal cysts, benign")
    return scene, specialist, study, assignment, published_preliminary, final


def test_publishing_the_final_supersedes_the_published_preliminary(api):
    """PRD §3.7: "Publication moves the report `DRAFT → PUBLISHED`, stamps
    `published_at` with the logical clock, sets `supersedes_report_id` to the id of
    the report that was `PUBLISHED` on this study immediately before — or null when
    there was none — and moves that predecessor `PUBLISHED → SUPERSEDED`, which keeps
    at most one live report per study."
    PRD §3.7: "and is stamped with a `report_version`: one more than the number of
    reports already on that study, **counting rows in every status including `DRAFT`,
    `SUPERSEDED` and `RETRACTED`**, assigned at creation in `created_at` ascending
    order, so the versions form a contiguous 1-based sequence per study."

    Design: Corner/state_machines/publishing_final_supersedes_the_published_preliminary_report
    """
    _scene, specialist, study, _assignment, preliminary, final = (
        _study_with_published_preliminary_and_drafted_final(api)
    )
    assert preliminary["report_version"] == 1
    assert preliminary["supersedes_report_id"] is None
    assert final["report_version"] == 2

    published_final = publish_report(final["id"], specialist["id"])

    assert published_final["status"] == "PUBLISHED"
    assert published_final["supersedes_report_id"] == preliminary["id"]
    assert validate_success(api.get_report(preliminary["id"], SCHED))["status"] == "SUPERSEDED"
    rows, _meta = validate_paginated(
        api.list_reports(SCHED, params={"study_id": study["id"], "status": "PUBLISHED"})
    )
    assert len(rows) == 1


def test_publishing_the_final_advances_the_study_and_completes_the_assignment(api):
    """PRD §3.7: "The study's workflow axis then advances according to the kind
    published: a preliminary moves it `READ_IN_PROGRESS → PRELIM_REPORTED`; a final
    moves it `READ_IN_PROGRESS → FINALIZED` or `PRELIM_REPORTED → FINALIZED`; an
    addendum leaves it unchanged. Publishing a final additionally moves the owning
    assignment `ACCEPTED → COMPLETED` and settles the turnaround axis as §3.8
    describes."
    PRD §3.8: "The opposite settlement happens at publication: when a final report is
    published and the study's `tat_accrued_minutes` is less than or equal to
    `tat_target_minutes` at that instant, the study moves `ACCRUING → MET` and the
    clock stops; when it is greater, the study moves `ACCRUING → BREACHED` instead."
    PRD §3.9: "Every publication appends a notification of kind `REPORT_PUBLISHED` for
    the clinic."

    Derivation: the whole scenario runs at one logical instant, so accrued turnaround
    is 0 against a routine target of 240 and the study settles MET.

    Design: Corner/state_machines/publishing_final_supersedes_the_published_preliminary_report
    """
    _scene, specialist, study, assignment, _preliminary, final = (
        _study_with_published_preliminary_and_drafted_final(api)
    )

    publish_report(final["id"], specialist["id"])

    fetched = validate_success(api.get_study(study["id"], SCHED))
    assert fetched["workflow_status"] == "FINALIZED"
    assert fetched["tat_status"] == "MET"
    assert validate_success(api.get_read_assignment(assignment["id"], SCHED))["status"] == "COMPLETED"
    rows, _meta = validate_paginated(
        api.list_notifications(SCHED, params={"study_id": study["id"], "kind": "REPORT_PUBLISHED"})
    )
    assert len(rows) == 2


def test_retracting_the_final_rewinds_the_study_to_prelim_reported(api):
    """PRD §3.7: "**Retraction** moves a report `PUBLISHED → RETRACTED`, stamping
    `retracted_at` and the supplied `retract_reason`. Either the report's own author
    or a `PlatformAdmin` may retract. When the retracted report was the study's final,
    the study's workflow axis rewinds: `FINALIZED → PRELIM_REPORTED` if a `PUBLISHED`
    or `SUPERSEDED` preliminary report exists on that study, and `FINALIZED →
    READ_IN_PROGRESS` otherwise."

    Design: Corner/state_machines/report_retraction_rewinds_the_study_workflow_axis
    """
    _scene, specialist, study, _assignment, preliminary, final = (
        _study_with_published_preliminary_and_drafted_final(api)
    )
    publish_report(final["id"], specialist["id"])

    retracted = validate_success(
        api.retract_report(final["id"], {"retract_reason": "wrong patient identifier"},
                           make_specialist_headers(specialist["id"]))
    )

    assert retracted["status"] == "RETRACTED"
    assert_same_instant(retracted["retracted_at"], "2026-05-04T09:00:00Z")
    assert validate_success(api.get_study(study["id"], SCHED))["workflow_status"] == "PRELIM_REPORTED"
    assert validate_success(api.get_report(preliminary["id"], SCHED))["status"] == "SUPERSEDED"
    rows, _meta = validate_paginated(
        api.list_reports(SCHED, params={"study_id": study["id"], "status": "PUBLISHED"})
    )
    assert rows == []


# --------------------------------------------------------------------------
# Peer review
# --------------------------------------------------------------------------
def _two_finished_studies_one_author_one_reviewer(api):
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(clinic_name="Peer Vet", address_zone="ZY",
                                technician_name="Hub QC Six",
                                body_regions=("ABDOMEN", "THORAX"), image_count=8)
    author = new_specialist("Dr Author", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    reviewer = new_specialist("Dr Reviewer", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    first, second = scene["studies"]
    offer_and_accept_read(first["id"], author["id"])
    first_report = draft_and_publish_report(first["id"], author["id"], "FINAL", "unremarkable abdomen")
    offer_and_accept_read(second["id"], author["id"])
    second_report = draft_and_publish_report(second["id"], author["id"], "FINAL", "unremarkable thorax")
    return scene, author, reviewer, first_report, second_report


def test_a_peer_review_score_of_two_is_discordant_and_three_is_concur(api):
    """PRD §3.7: "The named reviewer, and only they, then submits an integer `score`
    between 1 and 5 inclusive along with an optional `outcome_note`; a score outside
    that range is `ERR_VALIDATION`. A score of 2 or lower moves the review `SAMPLED →
    DISCORDANT`; a score of 3 or higher moves it `SAMPLED → CONCUR`."
    PRD §3.7: "The review is created in `SAMPLED` with a null `score` and a null
    `outcome_note`."

    Design: Corner/state_machines/peer_review_score_two_is_discordant_and_three_is_concur
    """
    _scene, _author, reviewer, first_report, second_report = (
        _two_finished_studies_one_author_one_reviewer(api)
    )
    first_review = validate_success(
        api.create_peer_review(
            {"report_id": first_report["id"], "reviewer_specialist_id": reviewer["id"]}, ADMIN
        ),
        expected_status=201,
    )
    second_review = validate_success(
        api.create_peer_review(
            {"report_id": second_report["id"], "reviewer_specialist_id": reviewer["id"]}, ADMIN
        ),
        expected_status=201,
    )
    assert first_review["status"] == "SAMPLED"

    discordant = validate_success(
        api.submit_peer_review(first_review["id"], {"score": 2, "outcome_note": "missed a nodule"},
                               make_specialist_headers(reviewer["id"]))
    )
    concur = validate_success(
        api.submit_peer_review(second_review["id"], {"score": 3, "outcome_note": "acceptable"},
                               make_specialist_headers(reviewer["id"]))
    )

    assert discordant["status"] == "DISCORDANT"
    assert discordant["score"] == 2
    assert concur["status"] == "CONCUR"
    assert concur["score"] == 3


def test_a_discordant_peer_review_leaves_the_study_and_report_untouched(api):
    """PRD §3.7: "**Peer review** is an independent quality axis with no billing or
    workflow consequence at all."
    PRD §3.7: "A discordant outcome has no billing and no workflow consequence
    whatsoever; peer review is a quality axis that records disagreement without acting
    on it."

    Design: Corner/state_machines/peer_review_score_two_is_discordant_and_three_is_concur
    """
    scene, _author, reviewer, first_report, _second_report = (
        _two_finished_studies_one_author_one_reviewer(api)
    )
    review = validate_success(
        api.create_peer_review(
            {"report_id": first_report["id"], "reviewer_specialist_id": reviewer["id"]}, ADMIN
        ),
        expected_status=201,
    )

    validate_success(
        api.submit_peer_review(review["id"], {"score": 2, "outcome_note": "missed a nodule"},
                               make_specialist_headers(reviewer["id"]))
    )

    study = validate_success(api.get_study(scene["studies"][0]["id"], SCHED))
    assert study["workflow_status"] == "FINALIZED"
    assert study["billing_status"] == "UNBILLED"
    assert validate_success(api.get_report(first_report["id"], SCHED))["status"] == "PUBLISHED"


def test_sampling_a_report_for_review_by_its_own_author_is_refused(api):
    """PRD §2.8 rung 39: "Segregation of duties.** A peer review's `reviewer_specialist_id` must differ from
    the report's `author_specialist_id`, otherwise `ERR_PEER_REVIEW_SELF` (422).
    Applies to `POST /peer-reviews`."

    Design: Corner/validations/peer_review_sampled_to_the_report_author_returns_self_review_error
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(clinic_name="SoD Vet", address_zone="V9",
                                technician_name="T Nine", image_count=5)
    specialist = new_specialist("Dr Solo", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    study = scene["studies"][0]
    offer_and_accept_read(study["id"], specialist["id"])
    report = draft_and_publish_report(study["id"], specialist["id"], "FINAL", "normal study")

    response = api.create_peer_review(
        {"report_id": report["id"], "reviewer_specialist_id": specialist["id"]}, ADMIN
    )

    validate_error(response, ApiErrorId.ERR_PEER_REVIEW_SELF.value)
    rows, _meta = validate_paginated(api.list_peer_reviews(SCHED, params={"report_id": report["id"]}))
    assert rows == []


# --------------------------------------------------------------------------
# The addendum window
# --------------------------------------------------------------------------
def test_an_addendum_published_exactly_fourteen_days_on_is_out_of_time(api):
    """PRD §3.7: "An `ADDENDUM` requires a report on the same study whose `kind` is
    `FINAL` and whose `status` is `PUBLISHED` or `SUPERSEDED`, and requires the
    logical clock to be **strictly before** that report's `published_at` plus 14 days
    — publishing at exactly the fourteen-day mark is closed, publishing one minute
    earlier is open."
    PRD §2.8 rung 38: "Addendum window.** An addendum may be published only while the logical clock is
    strictly before the final report's `published_at` plus 14 days; otherwise
    `ERR_ADDENDUM_WINDOW_CLOSED` (422). Applies to `POST
    /reports/{report_id}/publish`."
    PRD §2.8 rung 36: "The acting specialist must either hold an `ACCEPTED` read
    assignment on the study being reported, or already be the `author_specialist_id`
    of a report on that study whose status is `PUBLISHED`, `SUPERSEDED` or
    `RETRACTED`; otherwise `ERR_NOT_ASSIGNED_SPECIALIST` (403)."

    Derivation: the FINAL is published at 2026-05-04T09:00:00Z, so the window closes
    at exactly 2026-05-18T09:00:00Z; publishing the addendum at that very instant is
    not strictly before it.

    Design: Corner/validations/publishing_an_addendum_after_the_fourteen_day_window_returns_closed
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(clinic_name="Addendum Vet", address_zone="V8",
                                technician_name="T Eight", image_count=9)
    specialist = new_specialist("Dr Late", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    study = scene["studies"][0]
    offer_and_accept_read(study["id"], specialist["id"])
    final = draft_and_publish_report(study["id"], specialist["id"], "FINAL", "splenic mass")
    assert_same_instant(final["published_at"], "2026-05-04T09:00:00Z")

    set_clock("2026-05-18T09:00:00Z")
    addendum = draft_report(study["id"], specialist["id"], kind="ADDENDUM",
                            findings="cytology confirms haemangiosarcoma")
    assert addendum["report_version"] == 2

    response = api.publish_report(addendum["id"], make_specialist_headers(specialist["id"]))

    validate_error(response, ApiErrorId.ERR_ADDENDUM_WINDOW_CLOSED.value)
    assert validate_success(api.get_report(addendum["id"], SCHED))["status"] == "DRAFT"
    assert validate_success(api.get_report(final["id"], SCHED))["status"] == "PUBLISHED"


# --------------------------------------------------------------------------
# Second-attempt and wrong-axis mistakes each earn their own code
# --------------------------------------------------------------------------
def _finished_stat_study_with_a_submitted_peer_review(api):
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(clinic_name="Sweep Two Vet", address_zone="S2",
                                technician_name="T S2", image_count=7)
    author = new_specialist("Dr S2 Author", ("ULTRASOUND",), ("CANINE",), stat_eligible=True)
    stranger = new_specialist("Dr S2 Stranger", ("ULTRASOUND",), ("CANINE",), stat_eligible=True)
    study = scene["studies"][0]
    assignment = offer_and_accept_read(study["id"], author["id"])
    validate_success(
        api.escalate_stat(study["id"], make_clinic_user_headers(scene["clinic"]["id"]))
    )
    report = draft_and_publish_report(study["id"], author["id"], "FINAL", "normal")
    review = validate_success(
        api.create_peer_review({"report_id": report["id"], "reviewer_specialist_id": stranger["id"]},
                               ADMIN),
        expected_status=201,
    )
    validate_success(
        api.submit_peer_review(review["id"], {"score": 5, "outcome_note": "excellent"},
                               make_specialist_headers(stranger["id"]))
    )
    return scene, author, stranger, study, assignment, report, review


def test_accepting_an_assignment_that_is_no_longer_offered_is_refused(api):
    """PRD §2.8 rung 21: "**Read-assignment state precondition** — accept and decline require `OFFERED`,
    hand-back requires `ACCEPTED`; otherwise `ERR_ASSIGNMENT_INVALID_STATE` (409)."

    Design: Corner/errors/read_report_and_peer_review_state_and_clock_sweep
    """
    _scene, author, _stranger, _study, assignment, _report, _review = (
        _finished_stat_study_with_a_submitted_peer_review(api)
    )
    assert validate_success(api.get_read_assignment(assignment["id"], SCHED))["status"] == "COMPLETED"

    response = api.accept_assignment(assignment["id"], make_specialist_headers(author["id"]))

    validate_error(response, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE.value)


def test_publishing_an_already_published_report_is_refused(api):
    """PRD §2.8 rung 22: "Publishing requires the report to be `DRAFT` and retracting
    requires it to be `PUBLISHED`, otherwise `ERR_REPORT_INVALID_STATE` (409)."

    Design: Corner/errors/read_report_and_peer_review_state_and_clock_sweep
    """
    _scene, author, _stranger, _study, _assignment, report, _review = (
        _finished_stat_study_with_a_submitted_peer_review(api)
    )

    response = api.publish_report(report["id"], make_specialist_headers(author["id"]))

    validate_error(response, ApiErrorId.ERR_REPORT_INVALID_STATE.value)
    assert validate_success(api.get_report(report["id"], SCHED))["status"] == "PUBLISHED"


def test_resubmitting_a_peer_review_that_has_already_concurred_is_refused(api):
    """PRD §2.8 rung 22: "A peer-review submission requires the peer review to be
    `SAMPLED`, and sampling or submission requires the underlying report to be in
    `PUBLISHED`, `SUPERSEDED` or `RETRACTED`; otherwise
    `ERR_PEER_REVIEW_INVALID_STATE` (409)."

    Design: Corner/errors/read_report_and_peer_review_state_and_clock_sweep
    """
    _scene, _author, stranger, _study, _assignment, _report, review = (
        _finished_stat_study_with_a_submitted_peer_review(api)
    )
    submitted = validate_success(api.get_peer_review(review["id"], SCHED))
    assert submitted["status"] == "CONCUR"
    assert submitted["score"] == 5

    response = api.submit_peer_review(
        review["id"], {"score": 4, "outcome_note": "second opinion"},
        make_specialist_headers(stranger["id"]),
    )

    validate_error(response, ApiErrorId.ERR_PEER_REVIEW_INVALID_STATE.value)


def test_resuming_a_study_whose_clock_is_not_paused_is_refused(api):
    """PRD §2.8 rung 20: "first, a hold requested on a study whose `tat_status` is not `ACCRUING`, or a resume
    requested on a study whose `tat_status` is not `PAUSED`, raises
    `ERR_TAT_CLOCK_STATE_INVALID` (409)"
    PRD §3.8: "A hold requested on a study whose `tat_status` is not `ACCRUING`, or a
    resume on one whose `tat_status` is not `PAUSED`, is refused with
    `ERR_TAT_CLOCK_STATE_INVALID`."

    Design: Corner/errors/read_report_and_peer_review_state_and_clock_sweep
    """
    scene, _author, _stranger, study, _assignment, _report, _review = (
        _finished_stat_study_with_a_submitted_peer_review(api)
    )

    response = api.resume_study(
        study["id"], {"clinical_history": "nothing to add"},
        make_clinic_user_headers(scene["clinic"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_TAT_CLOCK_STATE_INVALID.value)


def test_escalating_a_study_that_is_already_stat_is_refused(api):
    """PRD §2.8 rung 20: "second, a STAT escalation requested on a study whose
    `priority` is already `STAT` raises `ERR_ALREADY_STAT` (409)."
    PRD §3.8: "Priority is a ratchet: it is raised to `STAT` and never lowered again."

    Design: Corner/errors/read_report_and_peer_review_state_and_clock_sweep
    """
    scene, _author, _stranger, study, _assignment, _report, _review = (
        _finished_stat_study_with_a_submitted_peer_review(api)
    )
    assert validate_success(api.get_study(study["id"], SCHED))["priority"] == "STAT"

    response = api.escalate_stat(study["id"], make_clinic_user_headers(scene["clinic"]["id"]))

    validate_error(response, ApiErrorId.ERR_ALREADY_STAT.value)


def test_a_specialist_with_no_relationship_to_the_study_cannot_draft_a_report(api):
    """PRD §2.8 rung 36: "**Authoring entitlement.** The acting specialist must either
    hold an `ACCEPTED` read assignment on the study being reported, or already be the
    `author_specialist_id` of a report on that study whose status is `PUBLISHED`,
    `SUPERSEDED` or `RETRACTED`; otherwise `ERR_NOT_ASSIGNED_SPECIALIST` (403)."
    PRD §3.7: "To draft at all, the acting specialist must satisfy rung 36: they must
    hold an `ACCEPTED` assignment on that study, **or** already be the author of a
    report on that study whose `status` is `PUBLISHED`, `SUPERSEDED` or `RETRACTED`."

    Design: Corner/errors/read_report_and_peer_review_state_and_clock_sweep
    """
    _scene, _author, stranger, study, _assignment, _report, _review = (
        _finished_stat_study_with_a_submitted_peer_review(api)
    )

    response = api.create_report(
        {"study_id": study["id"], "kind": "ADDENDUM", "findings": "stranger addendum"},
        make_specialist_headers(stranger["id"]),
    )

    validate_error(response, ApiErrorId.ERR_NOT_ASSIGNED_SPECIALIST.value)


def test_publishing_a_preliminary_once_the_study_is_finalized_breaks_the_sequence_rule(api):
    """PRD §3.7: "A `PRELIMINARY` report requires the study's `workflow_status` to be
    `READ_IN_PROGRESS`; it needs no predecessor report."
    PRD §3.7: "Anything that fails the shape test raises `ERR_REPORT_SEQUENCE_INVALID`;
    a late addendum raises `ERR_ADDENDUM_WINDOW_CLOSED`."

    Design: Corner/errors/read_report_and_peer_review_state_and_clock_sweep
    """
    _scene, author, _stranger, study, _assignment, _report, _review = (
        _finished_stat_study_with_a_submitted_peer_review(api)
    )
    assert validate_success(api.get_study(study["id"], SCHED))["workflow_status"] == "FINALIZED"
    late_preliminary = draft_report(study["id"], author["id"], kind="PRELIMINARY",
                                    findings="late preliminary")

    response = api.publish_report(late_preliminary["id"], make_specialist_headers(author["id"]))

    validate_error(response, ApiErrorId.ERR_REPORT_SEQUENCE_INVALID.value)
    assert validate_success(api.get_report(late_preliminary["id"], SCHED))["status"] == "DRAFT"
