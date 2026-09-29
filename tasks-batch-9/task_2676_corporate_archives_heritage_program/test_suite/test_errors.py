"""Every error code in §1.6 that no §1.8 instance already asserts positively.

Each test translates one instance of the corner-design ``errors`` section: the
seventeen-way not-found sweep, one trigger per state-invalid code, and the two
threshold codes whose §1.8 appearances only ever show them losing a priority
contest.
"""

from test_helpers import (
    ARCHIVIST_A,
    COUNSEL_A,
    DIRECTOR_A,
    MISSING_UUID,
    NOT_FOUND_BY_COLLECTION,
    OFFICER_A,
    OFFICER_B,
    PRESERV_B,
    assert_fields,
    assert_nulls,
    assert_score_2dp,
    assert_unit_custody_identity,
    factories as f,
    failed,
    fixtures as fx,
    ok,
)
from test_helpers.api_errors import (
    ERR_FINDING_AID_STATE_INVALID,
    ERR_INTERVIEW_STATE_INVALID,
    ERR_ITEM_STATE_INVALID,
    ERR_PACKAGE_STATE_INVALID,
    ERR_PRESERVATION_BUDGET_EXCEEDED,
    ERR_PROPOSAL_STATE_INVALID,
    ERR_RISK_THRESHOLD_REQUIRES_REDACTION,
    ERR_SCREENING_STATE_INVALID,
    ERR_SERIES_STATE_INVALID,
)


def test_each_collection_answers_an_unknown_path_id_with_its_own_not_found_code(client):
    """PRD §2.6: "Rules are therefore evaluated in a fixed ladder, and the **first** rule
    that fails determines the response."
    PRD §2.6: "4. **Path resolution** — the `{id}` in the request path resolves to an
    existing row of the endpoint's own resource type."
    PRD §2.6: "Failure: that resource type's not-found code (404), listed in §5 — for
    example `ERR_MIGRATION_JOB_NOT_FOUND` for a migration job path,
    `ERR_ACCESS_REQUEST_NOT_FOUND` for an access-request path."

    Design: Corner/errors/errors_all_seventeen_not_found_codes_triggerable_by_unknown_id
    """
    assert len(NOT_FOUND_BY_COLLECTION) == 17

    for collection_path, error_id in NOT_FOUND_BY_COLLECTION.items():
        failed(
            client.get_by_collection(collection_path, MISSING_UUID, DIRECTOR_A),
            error_id,
            404,
        )


def test_completing_an_already_completed_screening_neither_re_decides_nor_re_scores(
    client,
):
    """PRD §3.7: "Completing a screening is declared only from `OPEN` and additionally
    requires the parent request to be in `SCREENING` status; anything else yields
    `ERR_SCREENING_STATE_INVALID`."
    PRD §3.7: "Both passes start from the requester's class weight: 10 points for
    `INTERNAL_BUSINESS`, 30 for `EXTERNAL_RESEARCHER` and 45 for `MEDIA`."
    PRD §3.7: "It adds the greatest sensitivity weight found across the actual items
    named in `requested_item_ids`, using each item's own `sensitivity_level` and the same
    four weights, with no filter on item status — an item that has since drifted into
    `PENDING_DISPOSITION` still contributes its sensitivity."
    PRD §3.7: "When and only when the decision is `CHANGES_REQUESTED`, the parent request
    moves `SCREENING → CHANGES_REQUESTED`."

    Design: Corner/errors/errors_screening_complete_twice_returns_screening_state_invalid
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 1, "sensitivity_level": "PUBLIC",
                     "item_label": "AR-1960-2015"}],
        schedule_overrides={"code": "ERR-01", "retention_years": 40,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 6.1"},
        series_overrides={"title": "Annual Reports",
                          "business_unit": "Investor Relations",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 4,
                          "earliest_record_year": 1960,
                          "latest_record_year": 2015},
    )
    case = fx.screened_case(
        client,
        holding,
        decision="GRANT_FULL",
        redaction_required=False,
        screening_note="Public disclosures only.",
        requester_overrides={"display_name": "Internal Strategy Desk",
                             "requester_class": "INTERNAL_BUSINESS",
                             "affiliation": "Strategy",
                             "nda_on_file": False},
        purpose="Benchmark historical disclosures.",
    )
    assert_fields(case.screening, status="COMPLETED", decision="GRANT_FULL")
    assert_fields(case.request, status="SCREENING", post_screen_risk_score=10)

    failed(
        client.complete_screening(
            case.screening_id,
            f.complete_screening_payload(
                decision="DENY",
                redaction_required=False,
                screening_note="Attempted reversal.",
            ),
            OFFICER_A,
        ),
        ERR_SCREENING_STATE_INVALID,
        409,
    )

    assert_fields(
        fx.read_screening(client, case.screening_id),
        status="COMPLETED",
        decision="GRANT_FULL",
    )
    assert_fields(
        fx.read_request(client, case.request_id),
        status="SCREENING",
        post_screen_risk_score=10,
    )


def test_a_package_that_has_already_run_its_coverage_arithmetic_cannot_certify_again(
    client,
):
    """PRD §3.8: "Certification is the `LegalCounsel` operator's act, declared only from
    `DRAFT` — anything else yields `ERR_PACKAGE_STATE_INVALID` — and it runs the coverage
    arithmetic before either outcome is chosen."
    PRD §3.8: "The gaps are the runs of uncovered years, and there are three kinds, all
    of which count: the leading run, which is the earliest covered year minus the opening
    year; each interior run, which for every consecutive pair of covered years is the
    later year minus the earlier year, minus one; and the trailing run, which is the
    closing year minus the latest covered year."
    PRD §3.8: "When either fails, the package moves `DRAFT → REJECTED` and
    `rejection_code` records which gate stopped it: `GAP_EXCEEDED` when the gap gate
    failed, otherwise `COVERAGE_BELOW_MINIMUM`."
    PRD §3.8: "Package statuses are `DRAFT` and the two terminal states `CERTIFIED` and
    `REJECTED`."

    Design: Corner/errors/errors_certify_twice_returns_package_state_invalid
    """
    holding = fx.make_holding(
        client,
        stage="RECEIVED",
        item_specs=[
            {"unit_count": 1, "brand_use_year": 2018, "item_label": "PACK-2018"},
            {"unit_count": 1, "brand_use_year": 2021, "item_label": "PACK-2021"},
        ],
        schedule_overrides={"code": "ERR-02", "retention_years": 41,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 6.2"},
        series_overrides={"title": "Packaging Artwork",
                          "business_unit": "Brand",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 3,
                          "earliest_record_year": 2018,
                          "latest_record_year": 2021},
    )
    package = fx.make_package(
        client, holding.series_id, 2018, holding.item_ids, mark_name="WAVE DEVICE"
    )
    assert package["status"] == "DRAFT"

    first = ok(client.certify_evidence_package(package["id"], COUNSEL_A))
    assert_fields(
        first,
        status="REJECTED",
        rejection_code="GAP_EXCEEDED",
        qualifying_evidence_count=2,
        covered_year_count=2,
        max_gap_years=5,
    )
    assert_score_2dp(first, "continuous_use_coverage_pct", 22.22)

    failed(
        client.certify_evidence_package(package["id"], COUNSEL_A),
        ERR_PACKAGE_STATE_INVALID,
        409,
    )

    reloaded = fx.read_package(client, package["id"])
    assert_fields(
        reloaded,
        status="REJECTED",
        rejection_code="GAP_EXCEEDED",
        qualifying_evidence_count=2,
        max_gap_years=5,
    )
    assert_nulls(reloaded, "certified_at")


def test_a_dually_cleared_proposal_cannot_be_executed_before_it_is_approved(client):
    """PRD §3.9: "**Execution is the `Archivist`'s irreversible act**, declared only from
    `APPROVED`."
    PRD §3.9: "The item's destination depends on what is left: when `units_on_shelf`
    reaches exactly 0 the item lands in the terminal `DEACCESSIONED`; when units remain,
    the item returns to `ACCESSIONED`, which is how a partial deaccession works."
    PRD §3.9: "Approval stamps `approved_by` from `X-User-ID` and runs the three-hop
    staleness cascade."
    PRD §3.9: "Hop one moves the item `ACCESSIONED → PENDING_DISPOSITION`, with no unit
    movement yet."

    Design: Corner/errors/errors_deaccession_execute_before_approval_returns_proposal_state_invalid
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 3, "condition_grade": "FAIR",
                     "sensitivity_level": "PUBLIC", "item_label": "JOURNALS-DUP"}],
        schedule_overrides={"code": "ERR-03", "retention_years": 42,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 6.3"},
        series_overrides={"title": "Duplicate Trade Journals",
                          "business_unit": "Corporate Archives",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 9,
                          "earliest_record_year": 1962,
                          "latest_record_year": 1998},
        accession_overrides={"donor_name": "Library Unit"},
    )
    proposal = fx.make_proposal(
        client,
        holding.item_id,
        stage="DUALLY_CLEARED",
        units=3,
        route="DONATION",
        recipient_repository="Regional Business Library",
        rationale="Duplicates held by a partner library.",
    )
    assert proposal["status"] == "DUALLY_CLEARED"

    failed(
        client.execute_deaccession_proposal(
            proposal["id"], f.execute_payload("DON-2026-0031"), ARCHIVIST_A
        ),
        ERR_PROPOSAL_STATE_INVALID,
        409,
    )

    assert fx.read_proposal(client, proposal["id"])["status"] == "DUALLY_CLEARED"
    item = fx.read_item(client, holding.item_id)
    assert_fields(item, status="ACCESSIONED", units_on_shelf=3, units_deaccessioned=0)
    assert_unit_custody_identity(item)


def test_an_active_series_cannot_be_disposed_even_once_its_retention_has_elapsed(client):
    """PRD §3.1: "It is declared only from `ELIGIBLE_FOR_DISPOSITION`, so a series that is
    still `ACTIVE`, already `PERMANENT`, currently `SUSPENDED` or already `DISPOSED` is
    refused with `ERR_SERIES_STATE_INVALID`."
    PRD §3.1: "The series' `retention_expiry_utc` is that base instant advanced by
    `retention_years` whole calendar years, meaning the year field is incremented while
    the month, day and time-of-day are preserved verbatim."
    PRD §3.1: "At creation the series enters `disposition_state` `ACTIVE`, its
    `legal_hold_active` flag is false, its `current_appraisal_id` and
    `pre_hold_disposition_state` and `disposition_certificate_reference` are all null,
    its `blocked_access_request_count` is 0, and its `version` is 1."

    Design: Corner/errors/errors_dispose_active_series_returns_series_state_invalid
    """
    schedule = fx.make_schedule(
        client,
        code="ERR-04",
        retention_years=2,
        disposition_action="DESTROY",
        legal_citation="Corp Policy 6.4",
    )
    series = fx.make_series(
        client,
        schedule["id"],
        title="Expired Travel Claims",
        business_unit="Finance",
        sensitivity_ceiling="INTERNAL",
        annual_volume_linear_feet=12,
        earliest_record_year=2014,
        latest_record_year=2020,
    )
    assert_fields(series, disposition_state="ACTIVE")
    assert series["retention_expiry_utc"] == "2022-12-31T23:59:59.000Z"

    failed(
        client.dispose_record_series(
            series["id"], f.dispose_payload("DISP-2026-0099"), DIRECTOR_A
        ),
        ERR_SERIES_STATE_INVALID,
        409,
    )

    reloaded = fx.read_series(client, series["id"])
    assert_fields(reloaded, disposition_state="ACTIVE")
    assert_nulls(reloaded, "disposition_certificate_reference")


def test_signing_consent_twice_is_refused_and_leaves_the_transcription_axis_alone(
    client,
):
    """PRD §3.8: "Signing from `PENDING` moves consent to `SIGNED` and stamps
    `consent_signed_at` from the logical clock."
    PRD §3.8: "An action not declared from the interview's current consent value yields
    `ERR_INTERVIEW_STATE_INVALID`."
    PRD §3.8: "Every consent action recomputes `release_state` and leaves
    `transcription_status` completely untouched."
    PRD §3.8: "The interview is created with `consent_status` `PENDING`,
    `transcription_status` `NOT_STARTED`, `release_state` `WITHHELD`, `consent_signed_at`
    null and `withdrawal_count` 0."

    Design: Corner/errors/errors_consent_sign_from_signed_returns_interview_state_invalid
    """
    holding = fx.make_holding(
        client,
        stage="RECEIVED",
        item_specs=[{"unit_count": 1, "original_format": "MAGNETIC_TAPE",
                     "item_label": "OH-MASTER-TAPE"}],
        schedule_overrides={"code": "ERR-05", "retention_years": 43,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 6.5"},
        series_overrides={"title": "Retiree Oral Histories",
                          "business_unit": "Heritage",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 1,
                          "earliest_record_year": 2021,
                          "latest_record_year": 2026},
        accession_overrides={"donor_name": "Heritage Office",
                             "transfer_instrument": "DEED_OF_GIFT"},
    )
    interview = fx.interview_at(
        client,
        holding.accession_id,
        consent_actions=["SIGN"],
        narrator_name="R. Ferreira",
        interview_date="2026-07-15T00:00:00Z",
    )
    assert_fields(
        interview, consent_status="SIGNED", transcription_status="NOT_STARTED"
    )

    failed(
        client.interview_consent(
            interview["id"], f.consent_payload("SIGN"), ARCHIVIST_A
        ),
        ERR_INTERVIEW_STATE_INVALID,
        409,
    )

    reloaded = fx.read_interview(client, interview["id"])
    assert_fields(
        reloaded, consent_status="SIGNED", transcription_status="NOT_STARTED"
    )
    assert_nulls(reloaded, "embargo_until")


def test_a_confirmed_loan_cannot_be_checked_out_once_treatment_has_claimed_the_item(
    client,
):
    """PRD §2.6: "12. **State guard** — the target row must be in a state from which the
    requested transition is declared in §3."
    PRD §3.8: "On success the loan moves to `OUT`, `checked_out_at` is stamped from the
    logical clock, and the item moves `ACCESSIONED → ON_LOAN` with the loan's `units`
    subtracted from `units_on_shelf` and the same number added to `units_on_loan`,
    preserving the conservation identity of §2.10 exactly."
    PRD §3.6: "On success the job moves to `IN_PROGRESS` and the item moves `ACCESSIONED →
    IN_TREATMENT`, with no unit movement at all — the item stays shelved in its zone while
    under treatment."
    PRD §3.8: "No units move at confirmation."

    Design: Corner/errors/errors_check_out_while_item_in_treatment_returns_item_state_invalid
    """
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 2, "sensitivity_level": "PUBLIC",
             "item_label": "CHARTER-FACS"},
            {"unit_count": 1, "original_format": "FILM",
             "sensitivity_level": "PUBLIC", "item_label": "CHARTER-REELS"},
        ],
        schedule_overrides={"code": "ERR-06", "retention_years": 44,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 6.6"},
        series_overrides={"title": "Founding Charter Facsimiles",
                          "business_unit": "Heritage",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 2,
                          "earliest_record_year": 1926,
                          "latest_record_year": 1949},
        zone_overrides={"zone_code": "Z-ERR06", "temperature_c": 15.0,
                        "relative_humidity_pct": 40.0,
                        "max_overlapping_migration_jobs": 1},
        accession_overrides={"donor_name": "Heritage Office"},
    )
    assert holding.zone["environmental_status"] == "COMPLIANT"
    item_id = holding.item_ids[0]

    loan = fx.make_loan(
        client,
        item_id,
        "2026-08-01T00:00:00Z",
        "2026-08-20T00:00:00Z",
        stage="CONFIRMED",
        units=2,
        exhibit_name="Foundation Room",
    )
    plan = fx.make_plan(
        client, holding.zone_id, plan_name="Charter Digitisation", budget_cents=500000
    )
    job = fx.make_job(
        client,
        plan["id"],
        item_id,
        stage="IN_PROGRESS",
        units=2,
        target_format="PRESERVATION_TIFF",
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-12T00:00:00Z",
        approver=PRESERV_B,
    )
    assert job["status"] == "IN_PROGRESS"
    assert fx.read_item(client, item_id)["status"] == "IN_TREATMENT"

    failed(
        client.check_out_exhibit_loan(loan["id"], ARCHIVIST_A),
        ERR_ITEM_STATE_INVALID,
        409,
    )

    assert fx.read_loan(client, loan["id"])["status"] == "CONFIRMED"
    item = fx.read_item(client, item_id)
    assert_fields(item, status="IN_TREATMENT", units_on_shelf=2, units_on_loan=0)
    assert_unit_custody_identity(item)
    assert fx.read_job(client, job["id"])["status"] == "IN_PROGRESS"


def test_a_draft_finding_aid_cannot_skip_review_and_publish(client):
    """PRD §3.5: "Publication belongs to the `ArchivesDirector` and is declared only from
    `UNDER_REVIEW`."
    PRD §3.5: "Publication stamps `published_at` from the logical clock — on every
    publication, so a republished aid carries the most recent instant — and recomputes
    `described_item_count`."
    PRD §3.5: "`stale_item_count` is the number of items under that same accession whose
    status is `PENDING_DISPOSITION` or `DEACCESSIONED`."
    PRD §3.5: "Any other starting status yields `ERR_FINDING_AID_STATE_INVALID`."

    Design: Corner/errors/errors_publish_finding_aid_from_draft_returns_finding_aid_state_invalid
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 4, "condition_grade": "FAIR",
                     "item_label": "DRAWINGS-ROLLS"}],
        schedule_overrides={"code": "ERR-07", "retention_years": 45,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 6.7"},
        series_overrides={"title": "Plant Engineering Drawings",
                          "business_unit": "Operations",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 18,
                          "earliest_record_year": 1954,
                          "latest_record_year": 1988},
        accession_overrides={"donor_name": "Operations"},
    )
    aid = fx.make_finding_aid(
        client,
        holding.accession_id,
        title="Plant Engineering Drawings, 1954-1988",
        # PRD §3.5 declares exactly COLLECTION, SERIES, FILE and ITEM.
        arrangement_level="SERIES",
        version_label="v0.1",
    )
    assert aid["status"] == "DRAFT"

    failed(
        client.publish_finding_aid(aid["id"], DIRECTOR_A),
        ERR_FINDING_AID_STATE_INVALID,
        409,
    )

    reloaded = fx.read_finding_aid(client, aid["id"])
    assert_fields(reloaded, status="DRAFT", stale_item_count=0)
    assert_nulls(reloaded, "published_at")
    assert fx.read_accession(client, holding.accession_id)["status"] == "PROCESSED"


def test_a_full_approval_is_refused_the_moment_post_screen_risk_reaches_the_threshold(
    client,
):
    """PRD §3.7: "On top of that, a `FULL` approval requires `post_screen_risk_score` to be
    strictly below 75; at 75 or above, the only permitted outcome is a `REDACTED` approval,
    and an attempt at full scope is refused with `ERR_RISK_THRESHOLD_REQUIRES_REDACTION`."
    PRD §3.7: "It adds the greatest sensitivity weight found across the actual items named
    in `requested_item_ids`, using each item's own `sensitivity_level` and the same four
    weights, with no filter on item status — an item that has since drifted into
    `PENDING_DISPOSITION` still contributes its sensitivity."
    PRD §3.7: "Both branches stamp `decided_by` from `X-User-ID`, store the supplied
    `approval_scope`, and compute and store `service_fee_cents`."
    PRD §3.7: "The new screening stamps `screened_by` from `X-User-ID` and
    `max_item_sensitivity` — the highest `sensitivity_level` across the request's requested
    items, one of `PUBLIC`, `INTERNAL`, `CONFIDENTIAL` or `RESTRICTED` — and enters
    `status` `OPEN` with `redaction_required` false, and `decision`, `screening_note`,
    `superseded_reason` and `completed_at` all null."

    Design: Corner/errors/errors_full_approval_at_post_screen_eighty_returns_risk_threshold_requires_redaction
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "sensitivity_level": "CONFIDENTIAL",
                     "item_label": "MINUTES-1930-1990"}],
        schedule_overrides={"code": "ERR-08", "retention_years": 46,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 6.8"},
        series_overrides={"title": "Board Minute Books",
                          "business_unit": "Corporate Secretary",
                          "sensitivity_ceiling": "CONFIDENTIAL",
                          "annual_volume_linear_feet": 4,
                          "earliest_record_year": 1930,
                          "latest_record_year": 1990},
    )
    case = fx.screened_case(
        client,
        holding,
        decision="GRANT_FULL",
        redaction_required=False,
        screening_note="Content is confidential but releasable in full.",
        requester_overrides={"display_name": "T. Halvorsen",
                             "requester_class": "MEDIA",
                             "affiliation": "Business Daily",
                             "nda_on_file": False},
        purpose="Feature on governance history.",
    )
    assert_fields(case.screening, max_item_sensitivity="CONFIDENTIAL")
    assert_fields(case.request, prelim_risk_score=80, post_screen_risk_score=80)

    failed(
        client.approve_access_request(
            case.request_id, f.approve_request_payload("FULL"), OFFICER_B
        ),
        ERR_RISK_THRESHOLD_REQUIRES_REDACTION,
        422,
    )

    reloaded = fx.read_request(client, case.request_id)
    assert_fields(reloaded, status="SCREENING", post_screen_risk_score=80)
    assert_nulls(reloaded, "service_fee_cents", "approval_scope", "decided_by")


def test_the_second_job_is_refused_one_cent_over_the_plan_budget(client):
    """PRD §3.6: "The plan's `budget_committed_cents` plus this job's
    `committed_cost_cents` must not exceed the plan's `budget_cents`, with equality
    permitted; exceeding it yields `ERR_PRESERVATION_BUDGET_EXCEEDED`."
    PRD §3.6: "On success, `approved_by` is stamped from `X-User-ID` and the job's
    `committed_cost_cents` is added to the plan's `budget_committed_cents`."
    PRD §3.6: "The rates are 900 cents per unit for `PAPER`, 1,800 for `PHOTO`, 3,600 for
    `FILM`, 4,200 for `MAGNETIC_TAPE` and 600 for `BORN_DIGITAL`; the rate is keyed on the
    carrier being migrated *from*, never on `target_format`."
    PRD §3.6: "Step four selects `handling_fee_cents` from the step-three output: 1,500
    cents when `discounted_cents` is 25,000 or less, 4,000 cents when it lies between
    25,001 and 100,000 inclusive, and 9,000 cents when it is 100,001 or more."

    Design: Corner/errors/errors_second_job_one_cent_over_plan_budget_returns_preservation_budget_exceeded
    """
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 10, "item_label": "COUNCIL-A"},
            {"unit_count": 10, "item_label": "COUNCIL-B"},
            {"unit_count": 1, "original_format": "FILM",
             "item_label": "COUNCIL-REELS"},
        ],
        schedule_overrides={"code": "ERR-09", "retention_years": 47,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 6.9"},
        series_overrides={"title": "Works Council Files",
                          "business_unit": "Human Resources",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 14,
                          "earliest_record_year": 1972,
                          "latest_record_year": 2004},
        zone_overrides={"zone_code": "Z-ERR09", "temperature_c": 15.5,
                        "relative_humidity_pct": 41.0,
                        "max_overlapping_migration_jobs": 2},
    )
    plan = fx.make_plan(
        client,
        holding.zone_id,
        plan_name="Council File Digitisation",
        budget_cents=20999,
    )
    assert plan["status"] == "ACTIVE"

    job_a = fx.make_job(
        client,
        plan["id"],
        holding.item_ids[0],
        stage="APPROVED",
        units=10,
        target_format="PRESERVATION_TIFF",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-10T00:00:00Z",
        approver=PRESERV_B,
    )
    job_b = fx.make_job(
        client,
        plan["id"],
        holding.item_ids[1],
        units=10,
        target_format="PRESERVATION_TIFF",
        window_start="2026-09-20T00:00:00Z",
        window_end="2026-09-30T00:00:00Z",
    )
    assert job_a["committed_cost_cents"] == 10500
    assert job_b["committed_cost_cents"] == 10500

    failed(
        client.approve_migration_job(job_b["id"], PRESERV_B),
        ERR_PRESERVATION_BUDGET_EXCEEDED,
        422,
    )

    assert fx.read_job(client, job_a["id"])["status"] == "APPROVED"
    assert fx.read_job(client, job_b["id"])["status"] == "PENDING_APPROVAL"
    assert_fields(
        fx.read_plan(client, plan["id"]),
        budget_committed_cents=10500,
        budget_spent_cents=0,
    )
