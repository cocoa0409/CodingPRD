"""Who may act, on whose records, and on which of the two audit steps.

The role list is shown in both polarities -- one denial per role that owns
exclusive operations, and one acceptance per declared holder of every shared
operation -- and then the three rules that go beyond a plain role list: the
reporter's own-firm boundary, the four-eyes rule across the audit-to-penalty
handoff, and the public reader's publication-state boundary.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_clock_stamp,
    assert_penalty_breakdown,
    assert_penalty_ledger,
    assert_price_statistics,
    assert_submission_totals,
    assert_window_ledger,
)
from test_helpers.types import (
    AuditCaseStatus,
    AuditFinding,
    DelinquencyTier,
    DisclosureState,
    PublicationState,
    RegistrationStatus,
    ReportCategory,
    ReportingWindowStatus,
    SubmissionStatus,
    ViolationType,
    WeightingVariant,
)

ZERO_HEAD_HISTORY = {"2021": 0, "2022": 0, "2023": 0, "2024": 0, "2025": 0}


def test_01_a_role_privileged_elsewhere_is_still_denied_what_it_does_not_own(api):
    """Six exclusive operations, six denials, each by a role privileged elsewhere.

    An analyst may not register plants or move the clock, an administrator may not
    appeal for a firm or -- being neither -- take the reporter's side of any step,
    an auditor may not review a filing or assess money, and an officer may not open
    an audit case. Every identifier named is real, so the refusals prove the role
    check happens before the state and reference checks; the last one even carries a
    stale version field and never reports it.

    PRD §2.1: "If both headers are present and well formed but the presented role
    is not one of the roles authorized for the endpoint being called, the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/every_role_exclusive_operation_denied_to_a_non_holder
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing", activate=False)
    entity_id = firm["entity"]["id"]
    registration_id = firm["registration"]["id"]
    window = fx.create_standard_window(api)
    filing = fx.draft_filing(api, entity_id, firm["plant"]["id"], window["id"])
    entity_version = fx.entity_version(api, entity_id)

    denials = [
        api.create_plant(
            f.plant_payload(
                entity_id,
                plant_code="EST-199",
                annual_head_history=dict(ZERO_HEAD_HISTORY),
            ),
            u.MARKET_ANALYST,
        ),
        api.set_clock("2026-09-01T00:00:00Z", u.MARKET_ANALYST),
        api.appeal_registration(
            registration_id,
            f.appeal_payload(
                appeal_reason="administrator cannot appeal for the firm"
            ),
            u.PROGRAM_ADMIN,
        ),
        api.review_submission(
            filing["id"],
            f.review_payload(review_note="auditor cannot review"),
            u.COMPLIANCE_AUDITOR,
        ),
        api.create_audit_case(
            f.audit_case_payload(filing["id"]), u.PENALTY_OFFICER
        ),
        api.create_penalty_assessment(
            f.penalty_assessment_payload(
                entity_id,
                ViolationType.NON_REGISTRATION.value,
                entity_version + 99,
            ),
            u.COMPLIANCE_AUDITOR,
        ),
    ]
    for response in denials:
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    _plants, plant_meta = validate_paginated(api.list_plants(u.PROGRAM_ADMIN))
    assert plant_meta["total_count"] == 1, plant_meta

    clock_probe = fx.create_entity(api, legal_name="Clock Probe Co")
    assert clock_probe["created_at"].startswith("2026-08-01T00:00:00"), clock_probe

    resting_registration = fx.read_registration(api, registration_id)
    assert (
        resting_registration["status"] == RegistrationStatus.DETERMINED.value
    ), resting_registration
    assert resting_registration["appeal_count"] == 0, resting_registration
    assert (
        fx.read_submission(api, filing["id"])["status"]
        == SubmissionStatus.DRAFT.value
    )

    _cases, case_meta = validate_paginated(api.list_audit_cases(u.COMPLIANCE_AUDITOR))
    assert case_meta["total_count"] == 0, case_meta
    _penalties, penalty_meta = validate_paginated(
        api.list_penalty_assessments(u.PENALTY_OFFICER)
    )
    assert penalty_meta["total_count"] == 0, penalty_meta


def test_02_every_declared_holder_of_a_shared_operation_has_identical_effect(api):
    """Each shared step taken once by each of its declared holders.

    Two filings run the full correction cycle with the reporter and the
    administrator alternating on the reporter-side steps, the analyst and the
    administrator alternating on review, creation and aggregation, all three
    commenting roles filing one comment each, and the officer and the administrator
    each waiving one assessment -- and the resulting ledgers, price figures and
    point reversals do not record which holder called.

    PRD §2.1: "A `ProgramAdmin` may also act on a reporter's behalf anywhere along
    the filing chain and may waive a penalty."

    Design: Corner/rbac/shared_operations_accepted_from_every_declared_holder
    """
    firm = fx.firm_with_plants(
        api,
        [
            {"plant_code": "EST-101"},
            {
                "plant_code": "EST-102",
                "annual_head_history": dict(ZERO_HEAD_HISTORY),
            },
        ],
        legal_name="Alpha Packing",
    )
    entity_id = firm["entity"]["id"]
    reporter = u.reporter_agent(entity_id)
    window = fx.create_relaxed_window(api)
    docket = fx.open_docket(api)

    by_admin = get_success_data(
        api.create_submission(
            f.submission_payload(
                firm["plants"][0]["id"],
                window["id"],
                fx.window_version(api, window["id"]),
            ),
            u.PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    by_reporter = get_success_data(
        api.create_submission(
            f.submission_payload(
                firm["plants"][1]["id"],
                window["id"],
                fx.window_version(api, window["id"]),
            ),
            reporter,
        ),
        expected_status=201,
    )

    get_success_data(
        api.add_transaction(
            by_admin["id"],
            f.transaction_payload(
                head_count=100,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            ),
            u.PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    get_success_data(
        api.add_transaction(
            by_reporter["id"],
            f.transaction_payload(
                head_count=50,
                avg_net_price_per_cwt=279.50,
                avg_carcass_weight_cwt=8.10,
            ),
            reporter,
        ),
        expected_status=201,
    )

    validate_success(api.submit_submission(by_admin["id"], u.PROGRAM_ADMIN))
    validate_success(api.submit_submission(by_reporter["id"], reporter))
    validate_success(
        api.review_submission(
            by_admin["id"], f.review_payload(review_note="clean"), u.MARKET_ANALYST
        )
    )
    validate_success(
        api.review_submission(
            by_reporter["id"], f.review_payload(review_note="clean"), u.PROGRAM_ADMIN
        )
    )

    validate_success(
        api.open_correction(
            by_admin["id"],
            f.correction_payload(correction_reason="auditor-opened correction"),
            u.COMPLIANCE_AUDITOR,
        )
    )
    validate_success(
        api.open_correction(
            by_reporter["id"],
            f.correction_payload(
                correction_reason="administrator-opened correction"
            ),
            u.PROGRAM_ADMIN,
        )
    )
    validate_success(api.resubmit_submission(by_admin["id"], reporter))
    validate_success(api.resubmit_submission(by_reporter["id"], u.PROGRAM_ADMIN))

    for submission_id in (by_admin["id"], by_reporter["id"]):
        settled = validate_success(
            api.review_submission(
                submission_id,
                f.review_payload(review_note="restatement accepted"),
                u.MARKET_ANALYST,
            )
        )
        assert settled["status"] == SubmissionStatus.ACCEPTED.value, settled
        assert settled["resubmission_count"] == 1, settled

    assert_window_ledger(
        fx.read_window(api, window["id"]),
        total_head_reported=150,
        accepted_submission_count=2,
    )

    analyst_report = get_success_data(
        api.create_market_report(
            f.market_report_payload(
                window["id"],
                category=ReportCategory.LIVE_STEER_HEIFER.value,
                weighting_variant=WeightingVariant.HEAD_WEIGHTED.value,
            ),
            u.MARKET_ANALYST,
        ),
        expected_status=201,
    )
    admin_report = get_success_data(
        api.create_market_report(
            f.market_report_payload(
                window["id"],
                category=ReportCategory.LIVE_STEER_HEIFER.value,
                weighting_variant=WeightingVariant.WEIGHT_WEIGHTED.value,
            ),
            u.PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    by_head = validate_success(
        api.compute_market_report(analyst_report["id"], u.PROGRAM_ADMIN)
    )
    by_weight = validate_success(
        api.compute_market_report(admin_report["id"], u.MARKET_ANALYST)
    )
    for report in (by_head, by_weight):
        assert report["weighted_average_price_per_cwt"] == 279.83, report
        assert report["total_head"] == 150, report
        assert report["reporter_count"] == 1, report
        assert report["max_reporter_share_pct"] == 100.00, report
        assert report["source_submission_count"] == 2, report

    for headers, reference, stance in (
        (u.PUBLIC_USER, "public-1", "SUPPORT"),
        (reporter, "alpha-regulatory", "OPPOSE"),
        (u.PROGRAM_ADMIN, "program-office-note", "NEUTRAL"),
    ):
        get_success_data(
            api.create_public_comment(
                docket["id"],
                f.public_comment_payload(
                    commenter_reference=reference,
                    comment_text="filed by a declared commenting role",
                    stance=stance,
                ),
                headers,
            ),
            expected_status=201,
        )
    assert fx.read_methodology_change(api, docket["id"])["comment_count"] == 3

    first_penalty = fx.assess_penalty(
        api, entity_id, ViolationType.NON_REGISTRATION.value
    )
    assert_penalty_breakdown(
        first_penalty,
        repeat_index=0,
        repeat_multiplier=1.00,
        volume_factor=1.126,
        assessed_amount_cents=1126000,
        points=8,
        delinquency_tier_at_assessment=DelinquencyTier.TIER_0.value,
    )
    second_penalty = fx.assess_penalty(
        api, entity_id, ViolationType.NON_REGISTRATION.value
    )
    assert_penalty_breakdown(
        second_penalty,
        repeat_index=1,
        repeat_multiplier=1.50,
        volume_factor=1.126,
        assessed_amount_cents=1689000,
        points=8,
        delinquency_tier_at_assessment=DelinquencyTier.TIER_0.value,
    )

    officer_waiver = validate_success(
        api.waive_penalty_assessment(
            first_penalty["id"],
            f.waiver_payload(waiver_reason="waived by the penalty officer"),
            u.PENALTY_OFFICER,
        )
    )
    admin_waiver = validate_success(
        api.waive_penalty_assessment(
            second_penalty["id"],
            f.waiver_payload(waiver_reason="waived by the program administrator"),
            u.PROGRAM_ADMIN,
        )
    )
    for waived in (officer_waiver, admin_waiver):
        assert waived["status"] == "WAIVED", waived
        assert waived["settled_at"] is not None, waived

    assert_penalty_ledger(
        fx.read_entity(api, entity_id),
        assessed_penalty_cents=2815000,
        paid_penalty_cents=0,
        waived_penalty_cents=2815000,
        outstanding_penalty_cents=0,
        delinquency_points=0,
    )
    assert (
        fx.read_registration(api, firm["registration"]["id"])["status"]
        == RegistrationStatus.ACTIVE.value
    )


def test_03_a_reporter_holding_the_right_role_still_cannot_reach_a_peers_records(api):
    """The same role on the wrong firm: a 403 that is not the role gate.

    Bravo holds ReporterAgent, so its calls clear the identity and role rungs and
    are refused only because the plant, the filing and the determination file all
    belong to Alpha. The identical filing call on Bravo's own plant succeeds, and
    Bravo may still read Alpha's registry row -- the boundary is on writing another
    firm's records, not on reading the shared register.

    PRD §2.1: "Concretely, for filing operations the comparand is the owning firm
    of the filing's plant — the `reporting_entity_id` of the `Plant` named by the
    submission's `plant_id` — and for an appeal it is the `reporting_entity_id` of
    the registration itself."

    Design: Corner/rbac/foreign_reporting_entity_cannot_touch_another_firms_filings
    """
    alpha = fx.obligated_firm(api, legal_name="Alpha Packing", activate=False)
    bravo = fx.create_entity(api, legal_name="Bravo Beef")
    bravo_plant = fx.create_plant(api, bravo["id"], plant_code="EST-202")
    window = fx.create_standard_window(api)
    alpha_filing = fx.draft_filing(
        api, alpha["entity"]["id"], alpha["plant"]["id"], window["id"]
    )
    version_before = fx.window_version(api, window["id"])
    intruder = u.reporter_agent(bravo["id"])

    validate_error(
        api.create_submission(
            f.submission_payload(
                alpha["plant"]["id"], window["id"], version_before
            ),
            intruder,
        ),
        ApiErrorId.ERR_FOREIGN_REPORTING_ENTITY.value,
        403,
    )
    validate_error(
        api.add_transaction(
            alpha_filing["id"],
            f.transaction_payload(
                head_count=100,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            ),
            intruder,
        ),
        ApiErrorId.ERR_FOREIGN_REPORTING_ENTITY.value,
        403,
    )
    validate_error(
        api.appeal_registration(
            alpha["registration"]["id"],
            f.appeal_payload(appeal_reason="another firm's determination"),
            intruder,
        ),
        ApiErrorId.ERR_FOREIGN_REPORTING_ENTITY.value,
        403,
    )

    assert_submission_totals(
        fx.read_submission(api, alpha_filing["id"]), reported_head=0
    )
    assert fx.read_registration(api, alpha["registration"]["id"])["appeal_count"] == 0

    own_filing = get_success_data(
        api.create_submission(
            f.submission_payload(bravo_plant["id"], window["id"], version_before),
            intruder,
        ),
        expected_status=201,
    )
    assert own_filing["status"] == SubmissionStatus.DRAFT.value, own_filing
    assert own_filing["plant_id"] == bravo_plant["id"], own_filing

    peer_read = validate_success(
        api.get_reporting_entity(alpha["entity"]["id"], intruder)
    )
    assert peer_read["id"] == alpha["entity"]["id"], peer_read

    assert fx.window_version(api, window["id"]) == version_before + 1


def test_04_neither_audit_step_may_be_taken_by_the_hands_that_took_the_last(api):
    """Two four-eyes boundaries, each refused and then cleared by a second user.

    The auditor who opened the case cannot finalize it, and the user who finalized
    it cannot assess the resulting penalty even while presenting PenaltyOfficer --
    yet the penalty that a third pair of hands assesses is fully valued, so the rule
    gates the actor and not the amount.

    PRD §2.1: "**Segregation of duties** governs the audit-to-penalty handoff: the
    `X-User-ID` finalizing an audit case must differ from the `opened_by_user_id`
    recorded when that case was opened, and the `X-User-ID` assessing a penalty must
    differ from the `finalized_by_user_id` of the audit case that penalty
    references."

    Design: Corner/rbac/segregation_of_duties_blocks_the_same_user_on_both_steps
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    entity_id = firm["entity"]["id"]
    window = fx.create_relaxed_window(api)
    filing = fx.accepted_filing(
        api,
        entity_id,
        firm["plant"]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=100,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            )
        ],
    )
    assert_submission_totals(
        filing, reported_head=100, reported_value_dollars=224000.00
    )
    case = fx.fieldwork_case(api, filing["id"])
    assert case["opened_by_user_id"] == "auditor-1", case

    validate_error(
        api.finalize_audit_case(
            case["id"], f.finalize_audit_payload(90, 224000.00), u.COMPLIANCE_AUDITOR
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    still_open = fx.read_case(api, case["id"])
    assert still_open["status"] == AuditCaseStatus.FIELDWORK.value, still_open
    assert still_open["finalized_by_user_id"] is None, still_open

    settled = validate_success(
        api.finalize_audit_case(
            case["id"],
            f.finalize_audit_payload(90, 224000.00),
            u.COMPLIANCE_AUDITOR_2,
        )
    )
    assert settled["head_discrepancy_rate_pct"] == 11.11, settled
    assert settled["value_discrepancy_rate_pct"] == 0.00, settled
    assert settled["finding"] == AuditFinding.MATERIAL_HEAD.value, settled
    assert settled["status"] == AuditCaseStatus.DISCREPANCY.value, settled
    assert settled["opened_by_user_id"] == "auditor-1", settled
    assert settled["finalized_by_user_id"] == "auditor-2", settled

    validate_error(
        api.create_penalty_assessment(
            f.penalty_assessment_payload(
                entity_id,
                ViolationType.INACCURATE_DATA.value,
                fx.entity_version(api, entity_id),
                submission_id=filing["id"],
                audit_case_id=case["id"],
            ),
            u.penalty_officer("auditor-2"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    assessment = fx.assess_penalty(
        api,
        entity_id,
        ViolationType.INACCURATE_DATA.value,
        submission_id=filing["id"],
        audit_case_id=case["id"],
    )
    assert_penalty_breakdown(
        assessment,
        base_amount_cents=500000,
        volume_factor=1.126,
        assessed_amount_cents=563000,
        points=5,
        delinquency_tier_at_assessment=DelinquencyTier.TIER_0.value,
    )
    assert assessment["assessed_by_user_id"] == "officer-1", assessment
    assert_penalty_ledger(
        fx.read_entity(api, entity_id),
        outstanding_penalty_cents=563000,
        delinquency_points=5,
    )
    assert (
        fx.read_registration(api, firm["registration"]["id"])["status"]
        == RegistrationStatus.ACTIVE.value
    )


def test_05_the_public_reader_is_shown_a_report_only_once_it_is_released(api):
    """One report, two readers, and the instant that changes one of them.

    While the report is cleared but unpublished the identical read is a refusal for
    the public and a success for the analyst, and the public listing does not
    contain the row at all rather than containing it masked. Publication flips both
    the read and the listing for the public reader, with the same figures the analyst
    could already see.

    PRD §2.1: "**Public disclosure scoping** governs market news: when
    `X-User-Role` is `PublicUser`, a `MarketReport` is readable only while its
    `publication_state` is `PUBLISHED`; a report that is unpublished, withheld or
    withdrawn is invisible to the public and both the single-report read and the
    report list reject the attempt with `ERR_REPORT_NOT_PUBLISHED` (HTTP 403)."

    Design: Corner/rbac/public_user_sees_only_published_market_reports
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    window = fx.create_relaxed_window(api)
    fx.accepted_filing(
        api,
        firm["entity"]["id"],
        firm["plant"]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=200,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            )
        ],
    )
    report = fx.reviewed_report(api, window["id"])
    assert report["disclosure_state"] == DisclosureState.CLEARED.value, report
    assert (
        report["publication_state"] == PublicationState.UNPUBLISHED.value
    ), report

    validate_error(
        api.get_market_report(report["id"], u.PUBLIC_USER),
        ApiErrorId.ERR_REPORT_NOT_PUBLISHED.value,
        403,
    )
    analyst_view = validate_success(
        api.get_market_report(report["id"], u.MARKET_ANALYST)
    )
    assert analyst_view["weighted_average_price_per_cwt"] == 280.00, analyst_view
    assert analyst_view["total_head"] == 200, analyst_view

    hidden_rows, hidden_meta = validate_paginated(
        api.list_market_reports(u.PUBLIC_USER)
    )
    assert hidden_meta["total_count"] == 0, hidden_meta
    assert hidden_rows == [], hidden_rows

    fx.lock_window(api, window["id"])
    fx.set_clock(api, k.WINDOW_PUBLICATION_RELEASE)
    published = validate_success(
        api.publish_market_report(report["id"], u.MARKET_ANALYST)
    )
    assert (
        published["publication_state"] == PublicationState.PUBLISHED.value
    ), published
    assert_clock_stamp(
        published["published_at"], k.WINDOW_PUBLICATION_RELEASE, "published_at"
    )
    assert (
        fx.read_window(api, window["id"])["status"]
        == ReportingWindowStatus.PUBLISHED.value
    )

    public_view = validate_success(
        api.get_market_report(report["id"], u.PUBLIC_USER)
    )
    assert_price_statistics(public_view, 280.00, 280.00, 280.00)
    assert public_view["total_head"] == 200, public_view
    assert public_view["reporter_count"] == 1, public_view

    visible_rows, visible_meta = validate_paginated(
        api.list_market_reports(u.PUBLIC_USER)
    )
    assert visible_meta["total_count"] == 1, visible_meta
    assert [row["id"] for row in visible_rows] == [report["id"]], visible_rows
