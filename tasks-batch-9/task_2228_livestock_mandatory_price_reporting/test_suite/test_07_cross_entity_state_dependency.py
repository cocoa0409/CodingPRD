"""Operations blocked by the state of a different entity, then released by it.

In each pair the request is byte-identical both times: it is refused while the
foreign row is in the wrong state and succeeds once that row moves, so the
dependency is on the neighbour and not on the actor's own state.
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
    assert_discrepancy_rates,
    assert_lateness,
    assert_penalty_breakdown,
    assert_penalty_ledger,
    assert_window_ledger,
)
from test_helpers.types import (
    AuditCaseStatus,
    AuditFinding,
    DelinquencyTier,
    DeterminationOutcome,
    PublicationState,
    RegistrationStatus,
    ReportingWindowStatus,
    SubmissionStatus,
    ViolationType,
)

ZERO_HEAD_HISTORY = {"2021": 0, "2022": 0, "2023": 0, "2024": 0, "2025": 0}


def _draft_under_an_inactive_obligation(api):
    """A determined-but-not-activated firm holding a fully assembled draft."""
    firm = fx.obligated_firm(api, legal_name="Alpha Packing", activate=False)
    window = fx.create_standard_window(api)
    filing = fx.draft_filing(
        api, firm["entity"]["id"], firm["plant"]["id"], window["id"]
    )
    fx.add_transaction(
        api,
        firm["entity"]["id"],
        filing["id"],
        f.transaction_payload(
            head_count=100, avg_net_price_per_cwt=280.00, avg_carcass_weight_cwt=8.00
        ),
    )
    return {"firm": firm, "window": window, "filing": filing}


def test_01_filing_is_refused_while_the_obligation_record_is_only_determined(api):
    """Assembling a draft is allowed; filing it reads the registration's status.

    The determination already says the firm is mandatory, but until it is
    activated the filing cannot leave draft -- even though its 100 head are
    already attached and booked on the draft.

    PRD §3.5: "a missing, `SUSPENDED` or `REVOKED` registration blocks the filing
    with `ERR_REGISTRATION_NOT_ACTIVE`, even for a draft that was created while
    the registration was still good."

    Design: Difficulty/cross_entity_state_dependency/submission_submit_requires_active_registration
    """
    scene = _draft_under_an_inactive_obligation(api)
    registration = fx.read_registration(api, scene["firm"]["registration"]["id"])
    assert registration["status"] == RegistrationStatus.DETERMINED.value, registration
    assert registration["measured_head"] == 126000, registration

    refused = api.submit_submission(
        scene["filing"]["id"], u.reporter_agent(scene["firm"]["entity"]["id"])
    )
    validate_error(refused, ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE.value, 409)

    unmoved = fx.read_submission(api, scene["filing"]["id"])
    assert unmoved["status"] == SubmissionStatus.DRAFT.value, unmoved
    assert unmoved["submitted_at"] is None, unmoved
    assert unmoved["reported_head"] == 100, unmoved


def test_02_activating_the_registration_lets_the_same_request_through(api):
    """The identical submit succeeds once the neighbouring row moves.

    Activation mints the registration number and flips the status, and the
    unchanged filing request then goes through on time -- with the head still
    outside the window ledger, because only acceptance books it.

    PRD §3.2: "Activation is what actually obliges the firm's plants to file, and
    it carries the record from `DETERMINED` to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/submission_submit_requires_active_registration
    """
    scene = _draft_under_an_inactive_obligation(api)
    entity_id = scene["firm"]["entity"]["id"]

    api.submit_submission(scene["filing"]["id"], u.reporter_agent(entity_id))

    activated = validate_success(
        api.activate_registration(
            scene["firm"]["registration"]["id"], u.PROGRAM_ADMIN
        )
    )
    assert activated["status"] == RegistrationStatus.ACTIVE.value, activated
    assert activated["registration_number"] is not None, activated
    assert (
        activated["determination_outcome"] == DeterminationOutcome.MANDATORY.value
    ), activated

    filed = validate_success(
        api.submit_submission(scene["filing"]["id"], u.reporter_agent(entity_id))
    )
    assert filed["status"] == SubmissionStatus.SUBMITTED.value, filed
    assert_lateness(filed, lateness_minutes=0, is_late=False, days_late=0)

    assert_window_ledger(
        fx.read_window(api, scene["window"]["id"]),
        total_head_reported=0,
        accepted_submission_count=0,
    )


def _cleared_report_on_an_open_window(api):
    """A report ready in every respect except that its window is still open."""
    scene = fx.single_reporter_accepted_window(api)
    report = fx.reviewed_report(api, scene["window"]["id"])
    fx.set_clock(api, k.WINDOW_PUBLICATION_RELEASE)
    return scene, report


def test_03_release_is_refused_while_the_collection_window_is_still_open(api):
    """Everything on the report is ready; the parent window is not.

    The aggregate is computed, the disclosure review has cleared it and the clock
    is exactly at the release instant, yet the release is refused because the
    window is still collecting.

    PRD §3.6: "the window must be `LOCKED` or already `PUBLISHED`, since an `OPEN`
    window is still collecting, with an open window yielding
    `ERR_WINDOW_NOT_LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/report_publish_requires_locked_window
    """
    scene, report = _cleared_report_on_an_open_window(api)
    assert (
        fx.read_window(api, scene["window"]["id"])["status"]
        == ReportingWindowStatus.OPEN.value
    )

    refused = api.publish_market_report(report["id"], u.MARKET_ANALYST)
    validate_error(refused, ApiErrorId.ERR_WINDOW_NOT_LOCKED.value, 409)

    unmoved = fx.read_report(api, report["id"])
    assert unmoved["publication_state"] == PublicationState.UNPUBLISHED.value, unmoved
    assert unmoved["published_at"] is None, unmoved


def test_04_locking_the_window_releases_the_report_and_then_promotes_the_window(api):
    """The same foreign row is first a precondition and then a side-effect target.

    Locking the window lets the unchanged release request through, stamping the
    release instant on the report -- and the successful release carries that very
    window on from locked to published.

    PRD §3.3: "A window stops collecting when a `ProgramAdmin` locks it, taking it
    from `OPEN` to `LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/report_publish_requires_locked_window
    """
    scene, report = _cleared_report_on_an_open_window(api)
    window_id = scene["window"]["id"]

    api.publish_market_report(report["id"], u.MARKET_ANALYST)

    locked = validate_success(api.lock_reporting_window(window_id, u.PROGRAM_ADMIN))
    assert locked["status"] == ReportingWindowStatus.LOCKED.value, locked

    published = validate_success(
        api.publish_market_report(report["id"], u.MARKET_ANALYST)
    )
    assert published["publication_state"] == PublicationState.PUBLISHED.value, published
    assert_clock_stamp(
        published["published_at"], k.WINDOW_PUBLICATION_RELEASE, "published_at"
    )
    assert published["weighted_average_price_per_cwt"] == 280.00, published

    assert (
        fx.read_window(api, window_id)["status"]
        == ReportingWindowStatus.PUBLISHED.value
    )


def _one_reconciled_and_one_discrepant_case(api):
    """Two finalized audits on one firm: one immaterial, one material."""
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

    filings = []
    for plant in firm["plants"]:
        filings.append(
            fx.accepted_filing(
                api,
                entity_id,
                plant["id"],
                window["id"],
                lines=[
                    f.transaction_payload(
                        head_count=255,
                        avg_net_price_per_cwt=280.00,
                        avg_carcass_weight_cwt=8.00,
                    )
                ],
            )
        )

    clean = fx.discrepant_case(api, filings[0]["id"], 250, 571200.00)
    dirty = fx.discrepant_case(api, filings[1]["id"], 249, 571200.00)

    assert clean["status"] == AuditCaseStatus.RECONCILED.value, clean
    assert_discrepancy_rates(clean, 2.00, 0.00, AuditFinding.IMMATERIAL.value)
    assert dirty["status"] == AuditCaseStatus.DISCREPANCY.value, dirty
    assert_discrepancy_rates(dirty, 2.41, 0.00, AuditFinding.MATERIAL_HEAD.value)

    return {
        "firm": firm,
        "filings": filings,
        "clean": clean,
        "dirty": dirty,
    }


def test_05_an_inaccuracy_penalty_is_refused_against_a_reconciled_case(api):
    """A legitimate terminal audit outcome is still not evidence of inaccuracy.

    The reconciled case closed with an immaterial finding, so it cannot
    substantiate an inaccurate-data assessment; no assessment row is written and
    the firm's version does not move, so the version quoted stays current.

    PRD §3.8: "An `INACCURATE_DATA` assessment must name an `audit_case_id`
    referencing a case whose `status` is `DISCREPANCY` or `CLOSED` and whose
    `finding` is `MATERIAL_HEAD`, `MATERIAL_VALUE` or `MATERIAL_BOTH`."

    Design: Difficulty/cross_entity_state_dependency/penalty_requires_discrepant_audit_case
    """
    scene = _one_reconciled_and_one_discrepant_case(api)
    entity_id = scene["firm"]["entity"]["id"]
    version_before = fx.entity_version(api, entity_id)

    refused = api.create_penalty_assessment(
        f.penalty_assessment_payload(
            entity_id,
            ViolationType.INACCURATE_DATA.value,
            version_before,
            submission_id=scene["filings"][0]["id"],
            audit_case_id=scene["clean"]["id"],
        ),
        u.PENALTY_OFFICER,
    )
    validate_error(refused, ApiErrorId.ERR_AUDIT_CASE_NOT_DISCREPANT.value, 409)

    rows, meta = validate_paginated(
        api.list_penalty_assessments(
            u.PENALTY_OFFICER, params={"reporting_entity_id": entity_id}
        )
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows
    assert fx.entity_version(api, entity_id) == version_before


def test_06_the_same_penalty_against_the_discrepant_case_prices_off_a_third_row(api):
    """The material case substantiates it, and the registration sets the uplift.

    Against the discrepant case the assessment is written, taking its base from
    the violation class and its volume uplift from the registration's measured
    head, and its five points leave the firm far below the suspension tier.

    PRD §3.8: "Otherwise `volume_factor` is 1 plus the governing registration's
    `measured_head` divided by one million, with that uplift capped at 0.500".

    Design: Difficulty/cross_entity_state_dependency/penalty_requires_discrepant_audit_case
    """
    scene = _one_reconciled_and_one_discrepant_case(api)
    entity_id = scene["firm"]["entity"]["id"]

    api.create_penalty_assessment(
        f.penalty_assessment_payload(
            entity_id,
            ViolationType.INACCURATE_DATA.value,
            fx.entity_version(api, entity_id),
            submission_id=scene["filings"][0]["id"],
            audit_case_id=scene["clean"]["id"],
        ),
        u.PENALTY_OFFICER,
    )

    assessment = get_success_data(
        api.create_penalty_assessment(
            f.penalty_assessment_payload(
                entity_id,
                ViolationType.INACCURATE_DATA.value,
                fx.entity_version(api, entity_id),
                submission_id=scene["filings"][1]["id"],
                audit_case_id=scene["dirty"]["id"],
            ),
            u.PENALTY_OFFICER,
        ),
        expected_status=201,
    )

    assert_penalty_breakdown(
        assessment,
        base_amount_cents=500000,
        days_late=0,
        day_tier_multiplier=1.00,
        repeat_index=0,
        repeat_multiplier=1.00,
        volume_factor=1.126,
        suspension_surcharge=1.00,
        assessed_amount_cents=563000,
        points=5,
        delinquency_tier_at_assessment=DelinquencyTier.TIER_0.value,
    )

    assert_penalty_ledger(
        fx.read_entity(api, entity_id),
        assessed_penalty_cents=563000,
        outstanding_penalty_cents=563000,
        delinquency_points=5,
    )

    registration = fx.read_registration(api, scene["firm"]["registration"]["id"])
    assert registration["status"] == RegistrationStatus.ACTIVE.value, registration
