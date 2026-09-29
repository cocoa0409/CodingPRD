"""Where each record starts, which hops it allows and what a hop drags with it.

The happy-path transitions are checked for their full side-effect sets, the
guarded ones are refused for each guard in turn before being allowed through,
and the terminal ones are probed to confirm they accept nothing at all.
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
    assert_determination,
    assert_registration_number_format,
    assert_submission_totals,
    assert_window_ledger,
)
from test_helpers.types import (
    AggregationState,
    AuditCaseStatus,
    AuditFinding,
    BasisVariant,
    DeterminationOutcome,
    DisclosureState,
    MethodologyChangeStatus,
    PenaltyStatus,
    PublicationState,
    RegistrationStatus,
    ReportingWindowStatus,
    ReviewDecision,
    SubmissionStatus,
    ViolationType,
)

ZERO_HEAD_HISTORY = {"2021": 0, "2022": 0, "2023": 0, "2024": 0, "2025": 0}

DOCKET_COMMENT_CLOSE = "2026-08-31T00:00:00Z"
DOCKET_EFFECTIVE_FROM = "2026-09-30T00:00:00Z"


def test_01_every_record_opens_in_its_own_documented_starting_state(api):
    """Seven machines, seven starting positions, one of them a triple.

    A determination file opens as a draft, a window opens collecting, a filing
    opens as a draft with neither timestamp, an audit case opens queued under its
    opening auditor, an assessment opens unsettled, a docket opens with its
    comment period running -- and a market report opens on all three of its
    dimensions at once.

    PRD §3.6: "Its `aggregation_state` tracks whether the arithmetic is current
    and is `PENDING`, `COMPUTED` or `STALE`, starting at `PENDING`".

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    entity = fx.create_entity(api, legal_name="Alpha Packing")
    plant = fx.create_plant(api, entity["id"], plant_code="EST-101")
    window = fx.create_standard_window(api)

    registration = fx.draft_registration(api, entity["id"])
    assert registration["status"] == RegistrationStatus.DRAFT.value, registration
    assert window["status"] == ReportingWindowStatus.OPEN.value, window

    docket = fx.open_docket(api)
    assert docket["status"] == MethodologyChangeStatus.COMMENT_OPEN.value, docket
    assert docket["comment_count"] == 0, docket
    assert docket["industry_notice_issued_at"] is None, docket
    assert docket["restated_report_count"] == 0, docket

    report = fx.create_report(api, window["id"])
    assert report["aggregation_state"] == AggregationState.PENDING.value, report
    assert report["disclosure_state"] == DisclosureState.UNREVIEWED.value, report
    assert report["publication_state"] == PublicationState.UNPUBLISHED.value, report
    assert report["computed_at"] is None, report

    validate_success(api.determine_registration(registration["id"], u.PROGRAM_ADMIN))
    validate_success(api.activate_registration(registration["id"], u.PROGRAM_ADMIN))

    filing = fx.draft_filing(api, entity["id"], plant["id"], window["id"])
    assert filing["status"] == SubmissionStatus.DRAFT.value, filing
    assert filing["submitted_at"] is None, filing
    assert filing["accepted_at"] is None, filing

    fx.add_transaction(api, entity["id"], filing["id"], f.transaction_payload())
    validate_success(api.submit_submission(filing["id"], u.reporter_agent(entity["id"])))
    fx.accept_filing(api, filing["id"], review_note="clean")

    case = get_success_data(
        api.create_audit_case(
            f.audit_case_payload(filing["id"]), u.COMPLIANCE_AUDITOR
        ),
        expected_status=201,
    )
    assert case["status"] == AuditCaseStatus.OPEN.value, case
    assert case["opened_by_user_id"] == "auditor-1", case
    assert case["finding"] is None, case
    assert case["finalized_by_user_id"] is None, case

    assessment = fx.assess_penalty(
        api, entity["id"], ViolationType.NON_REGISTRATION.value
    )
    assert assessment["status"] == PenaltyStatus.ASSESSED.value, assessment
    assert assessment["settled_at"] is None, assessment
    assert assessment["waiver_reason"] is None, assessment


def test_02_determining_then_activating_carries_its_full_side_effects(api):
    """Determination measures; activation obliges and numbers.

    Determining stamps the measured volume against the species floor and the
    mandatory outcome while leaving the file unnumbered, and activating is what
    mints the registration number and dates the obligation from the clock.

    PRD §3.2: "Activation is what actually obliges the firm's plants to file, and
    it carries the record from `DETERMINED` to `ACTIVE`."

    Design: Corner/state_machines/registration_determine_then_activate_valid_transition
    """
    entity = fx.create_entity(api, legal_name="Alpha Packing")
    fx.create_plant(api, entity["id"], plant_code="EST-101")
    draft = fx.draft_registration(api, entity["id"])

    determined = validate_success(
        api.determine_registration(draft["id"], u.PROGRAM_ADMIN)
    )
    assert determined["status"] == RegistrationStatus.DETERMINED.value, determined
    assert_determination(determined, 126000, 125000, DeterminationOutcome.MANDATORY.value)
    assert determined["registration_number"] is None, determined
    assert determined["effective_from"] is None, determined
    assert determined["version"] > draft["version"], determined

    activated = validate_success(
        api.activate_registration(draft["id"], u.PROGRAM_ADMIN)
    )
    assert activated["status"] == RegistrationStatus.ACTIVE.value, activated
    assert_registration_number_format(activated["registration_number"], 2026, 1)
    assert_clock_stamp(activated["effective_from"], k.CLOCK_BASE_UTC, "effective_from")
    assert activated["version"] > determined["version"], activated


def test_03_rejecting_a_filing_records_the_note_and_moves_no_ledger(api):
    """The narrow branch: a rejection touches the filing and nothing else.

    The rejected filing keeps every line it reported and gains the reviewer's
    note, but it is never stamped as accepted and its hundred head never enter
    the window's ledger.

    PRD §3.5: "Rejection is likewise available from either `SUBMITTED` or
    `RESUBMITTED` and drives the filing to `REJECTED`: it records the
    `review_note` and does nothing else".

    Design: Corner/state_machines/review_reject_records_note_and_leaves_window_ledger_untouched
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    window = fx.create_standard_window(api)
    filed = fx.submitted_filing(
        api,
        firm["entity"]["id"],
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

    rejected = fx.reject_filing(
        api, filed["id"], review_note="carcass weight inconsistent with plant records"
    )

    assert rejected["status"] == SubmissionStatus.REJECTED.value, rejected
    assert (
        rejected["review_note"] == "carcass weight inconsistent with plant records"
    ), rejected
    assert rejected["accepted_at"] is None, rejected
    assert_clock_stamp(rejected["submitted_at"], k.CLOCK_BASE_UTC, "submitted_at")
    assert_submission_totals(
        rejected, reported_head=100, reported_value_dollars=224000.00
    )

    assert_window_ledger(
        fx.read_window(api, window["id"]),
        total_head_reported=0,
        accepted_submission_count=0,
    )


def test_04_neither_determine_nor_activate_is_a_no_op_on_a_second_call(api):
    """A replayed transition is a state error, not a repeat of the transition.

    Determining an already-determined file and activating an already-active one
    are both refused, and the refusals consume nothing: the registration number
    minted by the first activation is exactly the number still on the record.

    PRD §3.2: "any lifecycle action requested from a status that does not permit
    it — determining anything other than a `DRAFT`, appealing anything other than
    a `DETERMINED` record, redetermining anything other than an `UNDER_APPEAL`
    record, activating anything other than a `DETERMINED` record, suspending
    anything other than an `ACTIVE` record — is rejected with
    `ERR_INVALID_REGISTRATION_STATE`."

    Design: Corner/state_machines/determine_and_activate_are_not_idempotent_second_call_rejected
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    registration_id = firm["registration"]["id"]
    before = fx.read_registration(api, registration_id)

    validate_error(
        api.determine_registration(registration_id, u.PROGRAM_ADMIN),
        ApiErrorId.ERR_INVALID_REGISTRATION_STATE.value,
        409,
    )
    validate_error(
        api.activate_registration(registration_id, u.PROGRAM_ADMIN),
        ApiErrorId.ERR_INVALID_REGISTRATION_STATE.value,
        409,
    )

    after = fx.read_registration(api, registration_id)
    assert after["status"] == RegistrationStatus.ACTIVE.value, after
    assert_registration_number_format(after["registration_number"], 2026, 1)
    assert after["registration_number"] == before["registration_number"], after
    assert after["version"] == before["version"], after


def test_05_an_exempt_file_cannot_be_activated_and_appeals_are_capped_at_two(api):
    """Two guards on the appeal cycle, on a firm measuring 122,000 head.

    An exempt determination is refused activation outright, and the appeal loop
    runs exactly twice: the third appeal is refused while the counter stands at
    two and the record stays determined.

    PRD §3.2: "Each appeal increments `appeal_count` by 1, and the ceiling is two:
    an appeal filed when `appeal_count` has already reached 2 is rejected with
    `ERR_APPEAL_LIMIT_REACHED`."

    Design: Corner/state_machines/exempt_activation_and_appeal_ceiling_rejected
    """
    entity = fx.create_entity(api, legal_name="Bravo Beef")
    fx.create_plant(
        api,
        entity["id"],
        plant_code="EST-202",
        annual_head_history=dict(k.HISTORY_BELOW_CATTLE_FLOOR),
    )
    registration = fx.determined_registration(api, entity["id"])
    assert_determination(registration, 122000, 125000, DeterminationOutcome.EXEMPT.value)
    registration_id = registration["id"]
    reporter = u.reporter_agent(entity["id"])

    validate_error(
        api.activate_registration(registration_id, u.PROGRAM_ADMIN),
        ApiErrorId.ERR_ENTITY_EXEMPT.value,
        409,
    )

    for expected_count in (1, 2):
        appealed = validate_success(
            api.appeal_registration(
                registration_id,
                f.appeal_payload(appeal_reason="five-year basis understates volume"),
                reporter,
            )
        )
        assert appealed["status"] == RegistrationStatus.UNDER_APPEAL.value, appealed
        assert appealed["appeal_count"] == expected_count, appealed

        redetermined = validate_success(
            api.redetermine_registration(
                registration_id,
                f.redetermine_payload(
                    basis_variant=BasisVariant.FIVE_YEAR_AVERAGE.value
                ),
                u.PROGRAM_ADMIN,
            )
        )
        assert (
            redetermined["status"] == RegistrationStatus.DETERMINED.value
        ), redetermined
        assert_determination(
            redetermined, 122000, 125000, DeterminationOutcome.EXEMPT.value
        )

    validate_error(
        api.appeal_registration(
            registration_id,
            f.appeal_payload(appeal_reason="third appeal must be refused"),
            reporter,
        ),
        ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value,
        409,
    )

    final = fx.read_registration(api, registration_id)
    assert final["status"] == RegistrationStatus.DETERMINED.value, final
    assert final["appeal_count"] == 2, final


def test_06_three_terminal_records_accept_nothing_and_report_their_own_error(api):
    """A rejected filing, a closed case and an adopted docket, each sealed.

    Every further action against the three terminal records is refused with the
    error id belonging to that record's own machine, and none of the refusals
    edits a single field on the record it was aimed at.

    PRD §3.7: "`CLOSED` is terminal, and any action requested from a status that
    does not permit it — beginning fieldwork on anything but an `OPEN` case,
    finalizing anything but a `FIELDWORK` case, closing anything but a
    `RECONCILED` or `DISCREPANCY` case, or anything at all on a `CLOSED` case —
    is rejected with `ERR_INVALID_AUDIT_STATE`."

    Design: Corner/state_machines/terminal_states_reject_every_further_action
    """
    firm = fx.firm_with_plants(
        api,
        [
            {"plant_code": "EST-101"},
            {
                "plant_code": "EST-101B",
                "annual_head_history": dict(ZERO_HEAD_HISTORY),
                "boxed_beef_volume_lbs_prior_year": 0,
                "forward_commitment_cap_head": 500,
            },
        ],
        legal_name="Alpha Packing",
    )
    entity_id = firm["entity"]["id"]
    window = fx.create_standard_window(api)
    lines = [
        f.transaction_payload(
            head_count=100, avg_net_price_per_cwt=280.00, avg_carcass_weight_cwt=8.00
        )
    ]

    filed = fx.submitted_filing(
        api, entity_id, firm["plants"][0]["id"], window["id"], lines=lines
    )
    fx.reject_filing(api, filed["id"], review_note="rejected for terminal-state probe")

    audited = fx.accepted_filing(
        api, entity_id, firm["plants"][1]["id"], window["id"], lines=lines
    )
    case = fx.fieldwork_case(api, audited["id"])
    fx.finalize_case(api, case["id"], 100, 224000.00)
    closed = validate_success(
        api.close_audit_case(case["id"], u.COMPLIANCE_AUDITOR_2)
    )
    assert closed["status"] == AuditCaseStatus.CLOSED.value, closed

    docket = fx.open_docket(
        api,
        comment_period_end=DOCKET_COMMENT_CLOSE,
        effective_from=DOCKET_EFFECTIVE_FROM,
    )
    fx.add_comment(api, docket["id"])
    fx.set_clock(api, DOCKET_COMMENT_CLOSE)
    validate_success(api.close_comment_period(docket["id"], u.PROGRAM_ADMIN))
    adopted = validate_success(
        api.adopt_methodology_change(docket["id"], u.PROGRAM_ADMIN)
    )
    assert adopted["status"] == MethodologyChangeStatus.ADOPTED.value, adopted

    for response in (
        api.submit_submission(filed["id"], u.reporter_agent(entity_id)),
        api.review_submission(filed["id"], f.review_payload(), u.MARKET_ANALYST),
        api.open_correction(
            filed["id"],
            f.correction_payload(correction_reason="try to reopen a rejected filing"),
            u.COMPLIANCE_AUDITOR,
        ),
    ):
        validate_error(response, ApiErrorId.ERR_INVALID_SUBMISSION_STATE.value, 409)

    for response in (
        api.finalize_audit_case(
            case["id"], f.finalize_audit_payload(90, 200000.00), u.COMPLIANCE_AUDITOR_2
        ),
        api.close_audit_case(case["id"], u.COMPLIANCE_AUDITOR_2),
    ):
        validate_error(response, ApiErrorId.ERR_INVALID_AUDIT_STATE.value, 409)

    for response in (
        api.create_public_comment(
            docket["id"],
            f.public_comment_payload(
                commenter_reference="LATE-COMMENTER",
                comment_text="too late",
                stance="OPPOSE",
            ),
            u.PUBLIC_USER,
        ),
        api.close_comment_period(docket["id"], u.PROGRAM_ADMIN),
    ):
        validate_error(response, ApiErrorId.ERR_INVALID_METHODOLOGY_STATE.value, 409)

    sealed_filing = fx.read_submission(api, filed["id"])
    assert sealed_filing["status"] == SubmissionStatus.REJECTED.value, sealed_filing
    assert sealed_filing["resubmission_count"] == 0, sealed_filing
    assert (
        sealed_filing["review_note"] == "rejected for terminal-state probe"
    ), sealed_filing

    sealed_case = fx.read_case(api, case["id"])
    assert sealed_case["status"] == AuditCaseStatus.CLOSED.value, sealed_case
    assert sealed_case["finding"] == AuditFinding.IMMATERIAL.value, sealed_case
    assert sealed_case["verified_head"] == 100, sealed_case

    sealed_docket = fx.read_methodology_change(api, docket["id"])
    assert (
        sealed_docket["status"] == MethodologyChangeStatus.ADOPTED.value
    ), sealed_docket
    assert sealed_docket["comment_count"] == 1, sealed_docket


def test_07_locking_answers_its_temporal_guard_then_its_child_guard(api):
    """The same lock request is refused twice, for two different reasons.

    While the trade period is still running the lock is refused as premature; at
    exactly the period end the temporal guard passes and the hanging filing is
    what refuses it; once that filing is reviewed the lock goes through and the
    ledger it closes over reads the accepted head.

    PRD §3.3: "Locking also requires that no filing be left hanging: if any
    submission of the window is still in `SUBMITTED` or `RESUBMITTED` status,
    awaiting a reviewer's decision, the lock is refused with
    `ERR_PENDING_SUBMISSIONS_EXIST`."

    Design: Corner/state_machines/window_lock_preconditions_then_success
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    window = fx.create_standard_window(api)
    filed = fx.submitted_filing(
        api,
        firm["entity"]["id"],
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
    window_id = window["id"]
    version_before = fx.window_version(api, window_id)

    validate_error(
        api.lock_reporting_window(window_id, u.PROGRAM_ADMIN),
        ApiErrorId.ERR_WINDOW_PERIOD_NOT_ENDED.value,
        409,
    )

    fx.set_clock(api, k.WINDOW_PERIOD_END)
    validate_error(
        api.lock_reporting_window(window_id, u.PROGRAM_ADMIN),
        ApiErrorId.ERR_PENDING_SUBMISSIONS_EXIST.value,
        409,
    )
    assert fx.window_version(api, window_id) == version_before

    fx.accept_filing(api, filed["id"], review_note="clean")
    version_after_acceptance = fx.window_version(api, window_id)

    locked = validate_success(api.lock_reporting_window(window_id, u.PROGRAM_ADMIN))
    assert locked["status"] == ReportingWindowStatus.LOCKED.value, locked
    assert_window_ledger(locked, total_head_reported=100, accepted_submission_count=1)
    assert locked["version"] == version_after_acceptance + 1, locked


def test_08_release_answers_each_missing_prerequisite_in_its_own_turn(api):
    """Four refusals, one success at the release instant, then one replay refusal.

    Publication is the join of the report's three dimensions: it is refused first
    for arithmetic that is not current, then for a review that has not happened,
    then for a clock short of the release instant -- and once it goes through at
    exactly that instant the replay is refused because release is not idempotent.

    PRD §3.6: "the report must not already have been released, so a
    `publication_state` of `PUBLISHED` or `WITHDRAWN` yields
    `ERR_REPORT_ALREADY_PUBLISHED` — publication is deliberately not idempotent".

    Design: Corner/state_machines/publication_gate_sequence_rejects_out_of_order_actions
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
    report = fx.create_report(api, window["id"])
    report_id = report["id"]

    validate_error(
        api.publish_market_report(report_id, u.MARKET_ANALYST),
        ApiErrorId.ERR_REPORT_NOT_COMPUTED.value,
        409,
    )
    validate_error(
        api.disclosure_review_market_report(report_id, u.MARKET_ANALYST),
        ApiErrorId.ERR_REPORT_NOT_COMPUTED.value,
        409,
    )

    computed = validate_success(
        api.compute_market_report(report_id, u.MARKET_ANALYST)
    )
    assert computed["aggregation_state"] == AggregationState.COMPUTED.value, computed
    assert computed["weighted_average_price_per_cwt"] == 280.00, computed
    assert computed["total_head"] == 200, computed
    assert computed["reporter_count"] == 1, computed
    assert computed["max_reporter_share_pct"] == 100.00, computed
    assert computed["source_submission_count"] == 1, computed

    validate_error(
        api.publish_market_report(report_id, u.MARKET_ANALYST),
        ApiErrorId.ERR_DISCLOSURE_NOT_REVIEWED.value,
        409,
    )

    cleared = validate_success(
        api.disclosure_review_market_report(report_id, u.MARKET_ANALYST)
    )
    assert cleared["disclosure_state"] == DisclosureState.CLEARED.value, cleared
    assert cleared["suppression_reason"] is None, cleared

    validate_error(
        api.publish_market_report(report_id, u.MARKET_ANALYST),
        ApiErrorId.ERR_PUBLICATION_BEFORE_RELEASE_TIME.value,
        409,
    )

    fx.lock_window(api, window["id"])
    fx.set_clock(api, k.WINDOW_PUBLICATION_RELEASE)

    published = validate_success(api.publish_market_report(report_id, u.MARKET_ANALYST))
    assert published["publication_state"] == PublicationState.PUBLISHED.value, published
    assert_clock_stamp(
        published["published_at"], k.WINDOW_PUBLICATION_RELEASE, "published_at"
    )
    assert (
        fx.read_window(api, window["id"])["status"]
        == ReportingWindowStatus.PUBLISHED.value
    )

    validate_error(
        api.publish_market_report(report_id, u.MARKET_ANALYST),
        ApiErrorId.ERR_REPORT_ALREADY_PUBLISHED.value,
        409,
    )
    assert_clock_stamp(
        fx.read_report(api, report_id)["published_at"],
        k.WINDOW_PUBLICATION_RELEASE,
        "published_at",
    )


def test_09_a_superseding_filing_retires_its_predecessor_in_one_response(api):
    """Three ways to point a replacement filing, and only one of them works.

    A second original filing is refused as a duplicate, one pointed at the
    rejected predecessor is refused for the pointer rather than the duplication,
    and the one pointed at the accepted predecessor is created -- and on its
    acceptance the ledger swaps a hundred head for a hundred and twenty without
    ever holding both.

    PRD §3.5: "when the filing names a `supersedes_submission_id` the target must
    still be in `ACCEPTED` status at this instant, failing which the acceptance is
    refused with `ERR_SUPERSEDE_TARGET_NOT_ACCEPTED`, and on success that target
    moves `ACCEPTED → SUPERSEDED`".

    Design: Corner/state_machines/superseding_filing_marks_target_superseded
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    entity_id = firm["entity"]["id"]
    plant_id = firm["plant"]["id"]
    window = fx.create_standard_window(api)
    window_id = window["id"]
    reporter = u.reporter_agent(entity_id)
    lines = [
        f.transaction_payload(
            head_count=100, avg_net_price_per_cwt=280.00, avg_carcass_weight_cwt=8.00
        )
    ]

    rejected = fx.submitted_filing(api, entity_id, plant_id, window_id, lines=lines)
    fx.reject_filing(api, rejected["id"], review_note="first attempt refused")
    accepted = fx.accepted_filing(api, entity_id, plant_id, window_id, lines=lines)

    validate_error(
        api.create_submission(
            f.submission_payload(
                plant_id, window_id, fx.window_version(api, window_id)
            ),
            reporter,
        ),
        ApiErrorId.ERR_DUPLICATE_SUBMISSION.value,
        409,
    )
    validate_error(
        api.create_submission(
            f.submission_payload(
                plant_id,
                window_id,
                fx.window_version(api, window_id),
                supersedes_submission_id=rejected["id"],
            ),
            reporter,
        ),
        ApiErrorId.ERR_SUPERSEDE_TARGET_NOT_ACCEPTED.value,
        409,
    )

    replacement = get_success_data(
        api.create_submission(
            f.submission_payload(
                plant_id,
                window_id,
                fx.window_version(api, window_id),
                supersedes_submission_id=accepted["id"],
            ),
            reporter,
        ),
        expected_status=201,
    )
    assert replacement["supersedes_submission_id"] == accepted["id"], replacement
    assert replacement["status"] == SubmissionStatus.DRAFT.value, replacement

    fx.add_transaction(
        api,
        entity_id,
        replacement["id"],
        f.transaction_payload(
            head_count=120, avg_net_price_per_cwt=282.00, avg_carcass_weight_cwt=8.10
        ),
    )
    validate_success(api.submit_submission(replacement["id"], reporter))
    finished = validate_success(
        api.review_submission(
            replacement["id"],
            f.review_payload(
                decision=ReviewDecision.ACCEPT.value,
                review_note="supersedes the original filing",
            ),
            u.MARKET_ANALYST,
        )
    )
    assert_submission_totals(
        finished,
        reported_head=120,
        reported_cwt=972.00,
        reported_value_dollars=274104.00,
    )

    assert (
        fx.read_submission(api, accepted["id"])["status"]
        == SubmissionStatus.SUPERSEDED.value
    )
    assert_window_ledger(
        fx.read_window(api, window_id),
        total_head_reported=120,
        accepted_submission_count=1,
    )

    successors, meta = validate_paginated(
        api.list_submissions(
            u.PROGRAM_ADMIN, params={"supersedes_submission_id": accepted["id"]}
        )
    )
    assert meta["total_count"] == 1, meta
    assert successors[0]["id"] == replacement["id"], successors
