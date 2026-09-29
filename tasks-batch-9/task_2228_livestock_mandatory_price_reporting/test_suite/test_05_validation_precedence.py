"""Which single error surfaces when one request breaks two rules at once.

Each pair here is checked twice: once with both rules broken, to fix which one
wins, and once with only the lower-ranked rule broken, to prove the loser is
reachable at all.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.api_errors import ApiErrorId
from test_helpers.types import (
    DisclosureState,
    PublicationState,
    PurchaseType,
    ReportingWindowStatus,
    SubmissionStatus,
    SuppressionReason,
)

FORMULA_LINE_MISSING_ITS_REFERENCE = dict(
    purchase_type=PurchaseType.FORMULA.value,
    head_count=300,
    avg_net_price_per_cwt=292.25,
    avg_carcass_weight_cwt=9.40,
)

ZERO_HEAD_HISTORY = {"2021": 0, "2022": 0, "2023": 0, "2024": 0, "2025": 0}


def _one_open_and_one_closed_filing(api):
    """A DRAFT filing and a SUBMITTED filing of the same firm in one window."""
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
    plant_a, plant_b = firm["plants"]
    window = fx.create_window(api)

    return {
        "entity_id": entity_id,
        "open": fx.draft_filing(api, entity_id, plant_a["id"], window["id"]),
        "closed": fx.submitted_filing(api, entity_id, plant_b["id"], window["id"]),
    }


def test_01_a_closed_filing_reports_editability_not_the_missing_element(api):
    """The lifecycle gate is answered before the payload is inspected.

    A formula line with no base reference appended to a filing that has already
    been filed breaks both the editability rule and the data-element rule, and
    the reporter is told the filing is closed rather than being sent to fix a
    payload that would be refused anyway.

    PRD §2.9: "A `FORMULA` transaction line with no `formula_base_reference`
    posted to a submission that is no longer editable returns
    `ERR_SUBMISSION_NOT_EDITABLE`, not `ERR_MISSING_PURCHASE_TYPE_ELEMENT`."

    Design: Difficulty/priority_pair_validation_conflict/not_editable_outranks_missing_purchase_element
    """
    scene = _one_open_and_one_closed_filing(api)

    refused = api.add_transaction(
        scene["closed"]["id"],
        f.transaction_payload(**FORMULA_LINE_MISSING_ITS_REFERENCE),
        u.reporter_agent(scene["entity_id"]),
    )

    validate_error(refused, ApiErrorId.ERR_SUBMISSION_NOT_EDITABLE.value, 409)


def test_02_the_same_line_on_a_draft_filing_reports_the_missing_element(api):
    """With editability satisfied, the data-element rule is reachable.

    The identical payload on the still-editable filing is refused for the
    element it omits, and neither refusal leaves a line behind: the filed
    submission still holds its one original line and the draft holds none.

    PRD §3.4: "a `FORMULA` line must carry `formula_base_reference`, naming the
    base the formula references"

    Design: Difficulty/priority_pair_validation_conflict/not_editable_outranks_missing_purchase_element
    """
    scene = _one_open_and_one_closed_filing(api)
    line = f.transaction_payload(**FORMULA_LINE_MISSING_ITS_REFERENCE)

    api.add_transaction(
        scene["closed"]["id"], dict(line), u.reporter_agent(scene["entity_id"])
    )
    refused = api.add_transaction(
        scene["open"]["id"], dict(line), u.reporter_agent(scene["entity_id"])
    )

    validate_error(refused, ApiErrorId.ERR_MISSING_PURCHASE_TYPE_ELEMENT.value, 422)

    closed_lines, _meta = validate_paginated(
        api.list_transactions(scene["closed"]["id"], u.PROGRAM_ADMIN)
    )
    assert len(closed_lines) == 1, closed_lines
    open_lines, _meta = validate_paginated(
        api.list_transactions(scene["open"]["id"], u.PROGRAM_ADMIN)
    )
    assert open_lines == [], open_lines

    assert fx.read_submission(api, scene["closed"]["id"])["reported_head"] == 100
    assert fx.read_submission(api, scene["open"]["id"])["reported_head"] == 0


def _withheld_and_cleared_reports(api):
    """A withheld report and a cleared one, both before their release instants."""
    alpha = fx.alpha_firm(api)
    bravo = fx.bravo_firm(api)

    prior_window = fx.create_relaxed_window(
        api,
        period_start="2026-07-27T00:00:00Z",
        period_end="2026-08-03T00:00:00Z",
        submission_deadline_utc="2026-08-04T15:00:00Z",
        correction_deadline_utc="2026-08-11T15:00:00Z",
        publication_release_utc="2026-08-20T12:00:00Z",
    )
    fx.accepted_filing(
        api,
        alpha["entity"]["id"],
        alpha["plant"]["id"],
        prior_window["id"],
        lines=[f.transaction_payload(head_count=100)],
    )
    cleared = fx.reviewed_report(api, prior_window["id"])

    window = fx.create_standard_window(api)
    for firm in (alpha, bravo):
        fx.accepted_filing(
            api,
            firm["entity"]["id"],
            firm["plant"]["id"],
            window["id"],
            lines=[
                f.transaction_payload(
                    head_count=500,
                    avg_net_price_per_cwt=280.00,
                    avg_carcass_weight_cwt=8.00,
                )
            ],
        )
    withheld = fx.reviewed_report(api, window["id"])

    fx.set_clock(api, "2026-08-11T00:00:00Z")
    for target in (prior_window, window):
        get_success_data(api.lock_reporting_window(target["id"], u.PROGRAM_ADMIN))

    return {
        "prior_window": prior_window,
        "window": window,
        "cleared": cleared,
        "withheld": withheld,
    }


def test_03_a_withheld_report_reports_suppression_not_the_release_time(api):
    """The confidentiality bar answers before the clock is consulted.

    Only two firms reported into a window whose guideline demands three, so the
    review withheld the report; publishing it before its release instant breaks
    both rules and the answer names the bar that waiting cannot lift.

    PRD §2.9: "A withheld report that someone tries to publish before its release
    instant returns `ERR_CONFIDENTIALITY_SUPPRESSION_REQUIRED`, not
    `ERR_PUBLICATION_BEFORE_RELEASE_TIME`."

    Design: Difficulty/priority_pair_validation_conflict/suppression_outranks_release_time
    """
    scene = _withheld_and_cleared_reports(api)

    withheld = scene["withheld"]
    assert withheld["disclosure_state"] == DisclosureState.WITHHELD.value, withheld
    assert (
        withheld["suppression_reason"] == SuppressionReason.INSUFFICIENT_REPORTERS.value
    ), withheld
    assert withheld["reporter_count"] == 2, withheld
    assert withheld["weighted_average_price_per_cwt"] is None, withheld

    refused = api.publish_market_report(withheld["id"], u.MARKET_ANALYST)

    validate_error(
        refused, ApiErrorId.ERR_CONFIDENTIALITY_SUPPRESSION_REQUIRED.value, 409
    )


def test_04_a_cleared_report_before_its_release_reports_the_release_time(api):
    """With nothing suppressed, the temporal rule is reachable.

    The cleared report on the earlier window is refused purely for being early,
    and neither refusal moves a publication state or promotes a window.

    PRD §3.6: "the logical clock must have reached the window's
    `publication_release_utc`, with release exactly at that instant allowed and
    strictly earlier yielding `ERR_PUBLICATION_BEFORE_RELEASE_TIME`".

    Design: Difficulty/priority_pair_validation_conflict/suppression_outranks_release_time
    """
    scene = _withheld_and_cleared_reports(api)

    api.publish_market_report(scene["withheld"]["id"], u.MARKET_ANALYST)
    refused = api.publish_market_report(scene["cleared"]["id"], u.MARKET_ANALYST)

    validate_error(refused, ApiErrorId.ERR_PUBLICATION_BEFORE_RELEASE_TIME.value, 409)

    for key in ("withheld", "cleared"):
        report = fx.read_report(api, scene[key]["id"])
        assert report["publication_state"] == PublicationState.UNPUBLISHED.value, report

    for key in ("window", "prior_window"):
        window = fx.read_window(api, scene[key]["id"])
        assert window["status"] == ReportingWindowStatus.LOCKED.value, window


def _accepted_filing_and_a_rival_draft(api):
    """Alpha's accepted filing and Bravo's own draft, in one window."""
    alpha = fx.alpha_firm(api)
    bravo = fx.bravo_firm(api)
    window = fx.create_window(api)

    accepted = fx.accepted_filing(
        api, alpha["entity"]["id"], alpha["plant"]["id"], window["id"]
    )
    draft = fx.draft_filing(
        api, bravo["entity"]["id"], bravo["plant"]["id"], window["id"]
    )

    return {
        "window": window,
        "bravo_entity_id": bravo["entity"]["id"],
        "bravo_plant_id": bravo["plant"]["id"],
        "accepted": accepted,
        "draft": draft,
    }


def test_05_a_cross_plant_supersede_target_outranks_the_duplicate_rule(api):
    """The unusable pointer is rejected before the rule that would consult it.

    Bravo already holds an open filing for the window and names Alpha's accepted
    filing as its supersede target, so both rules are broken -- and the answer
    is the referential one, because the duplicate check itself reads that
    pointer.

    PRD §2.9: "A filing that names a supersede target belonging to another plant,
    on a plant that already holds an open filing for the window, returns
    `ERR_SUPERSEDE_TARGET_PLANT_MISMATCH`, not `ERR_DUPLICATE_SUBMISSION`."

    Design: Difficulty/priority_pair_validation_conflict/supersede_mismatch_outranks_duplicate_filing
    """
    scene = _accepted_filing_and_a_rival_draft(api)

    refused = api.create_submission(
        f.submission_payload(
            scene["bravo_plant_id"],
            scene["window"]["id"],
            fx.window_version(api, scene["window"]["id"]),
            supersedes_submission_id=scene["accepted"]["id"],
        ),
        u.reporter_agent(scene["bravo_entity_id"]),
    )

    validate_error(refused, ApiErrorId.ERR_SUPERSEDE_TARGET_PLANT_MISMATCH.value, 409)


def test_06_the_same_filing_without_a_target_reports_the_duplicate(api):
    """With no pointer to disagree about, the duplicate rule is reachable.

    Dropping the supersede target leaves only the open filing Bravo already
    holds, so the second attempt is refused as a duplicate; no third filing is
    created, Alpha's target keeps its accepted status, and the window version the
    rejected calls quoted is still current.

    PRD §3.4: "the creation is rejected with `ERR_DUPLICATE_SUBMISSION` when
    another filing for the same plant and window is in `DRAFT`, `SUBMITTED`,
    `UNDER_CORRECTION` or `RESUBMITTED` status".

    Design: Difficulty/priority_pair_validation_conflict/supersede_mismatch_outranks_duplicate_filing
    """
    scene = _accepted_filing_and_a_rival_draft(api)
    window_id = scene["window"]["id"]
    version_before = fx.window_version(api, window_id)

    api.create_submission(
        f.submission_payload(
            scene["bravo_plant_id"],
            window_id,
            version_before,
            supersedes_submission_id=scene["accepted"]["id"],
        ),
        u.reporter_agent(scene["bravo_entity_id"]),
    )
    refused = api.create_submission(
        f.submission_payload(scene["bravo_plant_id"], window_id, version_before),
        u.reporter_agent(scene["bravo_entity_id"]),
    )

    validate_error(refused, ApiErrorId.ERR_DUPLICATE_SUBMISSION.value, 409)

    filings, meta = validate_paginated(
        api.list_submissions(
            u.PROGRAM_ADMIN, params={"reporting_window_id": window_id}
        )
    )
    assert meta["total_count"] == 2, meta
    assert len(filings) == 2, filings

    assert (
        fx.read_submission(api, scene["accepted"]["id"])["status"]
        == SubmissionStatus.ACCEPTED.value
    )
    assert (
        fx.read_submission(api, scene["draft"]["id"])["status"]
        == SubmissionStatus.DRAFT.value
    )
    assert fx.window_version(api, window_id) == version_before
