"""Transparency reporting: closed periods, the two variants and publication gates."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_fields, assert_instant_equals, assert_rate_equals
from test_helpers.factories import (
    compute_report_payload,
    create_transparency_report_payload,
)
from test_helpers.fixtures import (
    build_assigned_case,
    build_computed_report,
    build_published_report,
    build_workforce_baseline,
)
from test_helpers.test_users import ADMIN_HEADERS, LEGAL_HEADERS

JUNE = {"period_start": "2026-06-01T00:00:00Z", "period_end": "2026-06-30T00:00:00Z"}
JULY = {"period_start": "2026-07-01T00:00:00Z", "period_end": "2026-07-31T00:00:00Z"}


def test_report_period_sharing_one_endpoint_instant_rejected(api, world, clock_at_t0):
    """Reporting periods are closed, so touching at a single instant intersects.

    PRD 3.9: "`period_end` must be strictly after `period_start`, or the request
    is `ERR_REPORT_PERIOD_INVALID` (HTTP 422), and the requested closed period may
    not intersect the closed period of any existing report — sharing even a single
    endpoint instant counts as an intersection — or the request is
    `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/report_period_closed_interval_shared_endpoint_rejected
    """
    first = world.create_report(**JUNE)
    assert_instant_equals(first["period_end"], JUNE["period_end"], "period_end")

    touching = api.create_transparency_report(
        create_transparency_report_payload(
            period_start="2026-06-30T00:00:00Z", period_end="2026-07-31T00:00:00Z"
        ),
        headers=ADMIN_HEADERS,
    )
    assert touching.status_code == 409
    validate_error(touching, ApiErrorId.REPORT_PERIOD_OVERLAP.value)

    degenerate = api.create_transparency_report(
        create_transparency_report_payload(
            period_start="2026-09-01T00:00:00Z", period_end="2026-09-01T00:00:00Z"
        ),
        headers=ADMIN_HEADERS,
    )
    assert degenerate.status_code == 422
    validate_error(degenerate, ApiErrorId.REPORT_PERIOD_INVALID.value)

    untouched = world.get_report(first["id"])
    assert_fields(
        untouched,
        {"status": "DRAFT", "enforcement_volume": 0, "computed_at": None},
        "the existing report",
    )


def test_report_period_starting_one_second_after_the_shared_instant_accepted(
    api, world, clock_at_t0
):
    """A period that clears the neighbouring endpoint by one second is opened.

    PRD 3.9: "A new report opens in `DRAFT` with a null `variant`, null
    `computed_at` and `published_at`, every volume counter at 0,
    `appeal_overturn_rate` and `legal_grant_rate` at `0.0000`, and an empty
    `category_rate_breakdown`."

    Design: Difficulty/resource_temporal_overlap/report_period_closed_interval_shared_endpoint_rejected
    """
    first = world.create_report(**JUNE)

    created = validate_success(
        api.create_transparency_report(
            create_transparency_report_payload(
                period_start="2026-06-30T00:00:01Z", period_end="2026-07-31T00:00:00Z"
            ),
            headers=ADMIN_HEADERS,
        ),
        201,
    )
    assert_fields(
        created,
        {
            "status": "DRAFT",
            "variant": None,
            "computed_at": None,
            "published_at": None,
            "enforcement_volume": 0,
            "removal_volume": 0,
            "age_gate_volume": 0,
            "warn_volume": 0,
            "overturn_adjusted_volume": 0,
            "appeal_count": 0,
            "legal_request_count": 0,
            "category_rate_breakdown": [],
        },
        "the accepted report",
    )
    assert_rate_equals(created["appeal_overturn_rate"], 0.0, "appeal_overturn_rate")
    assert_rate_equals(created["legal_grant_rate"], 0.0, "legal_grant_rate")

    fetched = world.get_report(created["id"])
    assert_instant_equals(fetched["period_start"], "2026-06-30T00:00:01Z", "period_start")
    assert_instant_equals(fetched["period_end"], "2026-07-31T00:00:00Z", "period_end")
    assert world.get_report(first["id"])["status"] == "DRAFT"


def test_publish_of_draft_report_rejected(api, world, clock_at_t0):
    """Publication needs computed figures before it can look at the variant.

    PRD 3.9: "Three conditions guard it: the report must be `COMPUTED`, or the
    attempt is `ERR_REPORT_NOT_COMPUTED` (HTTP 409); its recorded `variant` must be
    `RESTATED`, because provisional figures are not publishable, or the attempt is
    `ERR_REPORT_NOT_RESTATED` (HTTP 422); and no appeal on a case decided inside
    the period may still be sitting in `SUBMITTED` or `INDEPENDENT_REVIEW`, or the
    attempt is `ERR_OPEN_APPEALS_IN_PERIOD` (HTTP 422)."

    Design: Corner/errors/publish_of_draft_report_rejected
    """
    report = world.create_report(**JULY)

    refused = api.publish_transparency_report(report["id"], headers=ADMIN_HEADERS)
    assert refused.status_code == 409
    validate_error(refused, ApiErrorId.REPORT_NOT_COMPUTED.value)
    assert refused.json()["data"]["error_id"] != ApiErrorId.REPORT_NOT_RESTATED.value

    unchanged = world.get_report(report["id"])
    assert_fields(
        unchanged,
        {"status": "DRAFT", "published_at": None, "variant": None},
        "report after the refused publish",
    )

    world.compute_report(report["id"], variant="RESTATED")
    published = validate_success(
        api.publish_transparency_report(report["id"], headers=ADMIN_HEADERS)
    )
    assert published["status"] == "PUBLISHED"


def test_publish_of_provisional_report_rejected(api, world, clock_at_t0):
    """Provisional figures are computed but never publishable.

    PRD 3.9: "Three conditions guard it: the report must be `COMPUTED`, or the
    attempt is `ERR_REPORT_NOT_COMPUTED` (HTTP 409); its recorded `variant` must be
    `RESTATED`, because provisional figures are not publishable, or the attempt is
    `ERR_REPORT_NOT_RESTATED` (HTTP 422); and no appeal on a case decided inside
    the period may still be sitting in `SUBMITTED` or `INDEPENDENT_REVIEW`, or the
    attempt is `ERR_OPEN_APPEALS_IN_PERIOD` (HTTP 422)."

    Design: Corner/errors/publish_of_provisional_report_rejected
    """
    report = build_computed_report(world, variant="PROVISIONAL", **JULY)
    assert report["status"] == "COMPUTED"
    assert report["variant"] == "PROVISIONAL"

    refused = api.publish_transparency_report(report["id"], headers=LEGAL_HEADERS)
    assert refused.status_code == 422
    validate_error(refused, ApiErrorId.REPORT_NOT_RESTATED.value)
    still_computed = world.get_report(report["id"])
    assert_fields(
        still_computed,
        {"status": "COMPUTED", "variant": "PROVISIONAL", "published_at": None},
        "report after the refused publish",
    )

    world.compute_report(report["id"], variant="RESTATED")
    published = validate_success(
        api.publish_transparency_report(report["id"], headers=LEGAL_HEADERS)
    )
    assert published["status"] == "PUBLISHED"
    assert published["variant"] == "RESTATED"


def test_republish_of_published_report_rejected(api, world, clock_at_t0):
    """A published report is frozen against both a republish and a recompute.

    PRD 3.9: "On success `published_at` is stamped from the logical clock and
    every figure is frozen: a `PUBLISHED` report can neither be recomputed nor
    republished, and both attempts yield `ERR_REPORT_ALREADY_PUBLISHED`."

    Design: Corner/errors/republish_of_published_report_rejected
    """
    report = build_published_report(world, **JULY)
    assert_fields(
        report,
        {
            "status": "PUBLISHED",
            "variant": "RESTATED",
            "enforcement_volume": 0,
            "appeal_count": 0,
            "category_rate_breakdown": [],
        },
        "the published empty period",
    )
    assert_rate_equals(report["appeal_overturn_rate"], 0.0, "appeal_overturn_rate")
    assert_rate_equals(report["legal_grant_rate"], 0.0, "legal_grant_rate")
    assert_instant_equals(report["published_at"], "2026-08-01T09:00:00Z", "published_at")

    republish = api.publish_transparency_report(report["id"], headers=ADMIN_HEADERS)
    assert republish.status_code == 409
    validate_error(republish, ApiErrorId.REPORT_ALREADY_PUBLISHED.value)

    recompute = api.compute_transparency_report(
        report["id"], compute_report_payload(variant="PROVISIONAL"), headers=ADMIN_HEADERS
    )
    assert recompute.status_code == 409
    validate_error(recompute, ApiErrorId.REPORT_ALREADY_PUBLISHED.value)

    frozen = world.get_report(report["id"])
    assert_fields(
        frozen,
        {"status": "PUBLISHED", "variant": "RESTATED"},
        "report after both rejections",
    )
    assert_instant_equals(frozen["published_at"], "2026-08-01T09:00:00Z", "published_at")


def _window_with_one_overturned_removal(world):
    """A single-day window holding an overturned REMOVE and a surviving WARN."""
    base = build_workforce_baseline(world)
    removal = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides={"graphic_weight": 1}
    )
    world.decide(removal.case_id, base.frontline_id, outcome="REMOVE")
    warning = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides={"graphic_weight": 1}
    )
    world.decide(warning.case_id, base.frontline_id, outcome="WARN")

    appeal = world.file_appeal(removal.case_id, base.account_id)
    world.route_appeal(appeal["id"], base.auditor_id, target_reviewer_id=base.senior_id)
    world.resolve_appeal(
        appeal["id"], base.senior_id, resolution="OVERTURNED", resolution_note="Satire"
    )
    report = world.create_report(
        period_start="2026-08-01T00:00:00Z", period_end="2026-08-01T23:59:59Z"
    )
    return base, removal, warning, report


def test_provisional_and_restated_volumes_diverge_over_one_window(api, world):
    """The same two decisions count differently once one of them is overturned.

    PRD 3.9: "Under `PROVISIONAL` the base is the whole window, so decisions later
    overturned still count. Under `RESTATED` the base is the window restricted to
    cases whose `is_overturned` is false."

    Design: Difficulty/dual_variant_calc/transparency_provisional_vs_restated_volume_diverge
    """
    base, removal, warning, report = _window_with_one_overturned_removal(world)
    assert world.get_case(removal.case_id)["is_overturned"] is True
    assert world.get_case(warning.case_id)["is_overturned"] is False

    provisional = world.compute_report(report["id"], variant="PROVISIONAL")
    assert_fields(
        provisional,
        {
            "variant": "PROVISIONAL",
            "enforcement_volume": 2,
            "removal_volume": 1,
            "warn_volume": 1,
            "age_gate_volume": 0,
            "overturn_adjusted_volume": 1,
        },
        "provisional figures",
    )

    restated = world.compute_report(report["id"], variant="RESTATED")
    assert_fields(
        restated,
        {
            "variant": "RESTATED",
            "enforcement_volume": 1,
            "removal_volume": 0,
            "warn_volume": 1,
            "overturn_adjusted_volume": 1,
        },
        "restated figures",
    )


def test_recompute_overwrites_every_figure_and_switches_the_variant(api, world):
    """The second computation replaces the stored variant and all of its numbers.

    PRD 3.9: "Computation moves the report `DRAFT → COMPUTED`, and it may be
    repeated: a `COMPUTED` report may be recomputed under the other `variant`,
    which overwrites every figure and switches the recorded `variant`."

    Design: Difficulty/dual_variant_calc/transparency_provisional_vs_restated_volume_diverge
    """
    base, removal, warning, report = _window_with_one_overturned_removal(world)

    world.compute_report(report["id"], variant="PROVISIONAL")
    world.compute_report(report["id"], variant="RESTATED")

    stored = world.get_report(report["id"])
    assert_fields(
        stored,
        {
            "status": "COMPUTED",
            "variant": "RESTATED",
            "enforcement_volume": 1,
            "removal_volume": 0,
            "age_gate_volume": 0,
            "warn_volume": 1,
            "overturn_adjusted_volume": 1,
            "appeal_count": 1,
            "legal_request_count": 0,
            "published_at": None,
        },
        "report after the recompute",
    )
    assert_rate_equals(stored["appeal_overturn_rate"], 1.0, "appeal_overturn_rate")
    assert_rate_equals(stored["legal_grant_rate"], 0.0, "legal_grant_rate")
    assert_instant_equals(stored["computed_at"], "2026-08-01T09:00:00Z", "computed_at")


def _computed_report_over_an_open_appeal(world):
    """A RESTATED report over a period whose only decision is still under appeal."""
    base = build_workforce_baseline(world)
    scenario = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides={"graphic_weight": 2}
    )
    world.decide(scenario.case_id, base.frontline_id, outcome="REMOVE")
    appeal = world.file_appeal(scenario.case_id, base.account_id)
    world.route_appeal(appeal["id"], base.auditor_id, target_reviewer_id=base.senior_id)
    report = world.create_report(
        period_start="2026-08-01T00:00:00Z", period_end="2026-08-31T00:00:00Z"
    )
    computed = world.compute_report(report["id"], variant="RESTATED")
    return base, scenario, appeal["id"], computed


def test_publish_blocked_by_an_open_appeal_on_a_case_inside_the_period(api, world):
    """An appeal the report never references by key still blocks publication.

    PRD 3.9: "Three conditions guard it: the report must be `COMPUTED`, or the
    attempt is `ERR_REPORT_NOT_COMPUTED` (HTTP 409); its recorded `variant` must be
    `RESTATED`, because provisional figures are not publishable, or the attempt is
    `ERR_REPORT_NOT_RESTATED` (HTTP 422); and no appeal on a case decided inside
    the period may still be sitting in `SUBMITTED` or `INDEPENDENT_REVIEW`, or the
    attempt is `ERR_OPEN_APPEALS_IN_PERIOD` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/publish_blocked_by_open_appeal_in_period
    """
    base, scenario, appeal_id, computed = _computed_report_over_an_open_appeal(world)
    assert computed["status"] == "COMPUTED"
    assert computed["variant"] == "RESTATED"
    assert computed["enforcement_volume"] == 1
    assert computed["appeal_count"] == 0

    refused = api.publish_transparency_report(computed["id"], headers=ADMIN_HEADERS)
    assert refused.status_code == 422
    validate_error(refused, ApiErrorId.OPEN_APPEALS_IN_PERIOD.value)
    assert world.get_appeal(appeal_id)["status"] == "INDEPENDENT_REVIEW"

    unchanged = world.get_report(computed["id"])
    assert unchanged["status"] == "COMPUTED"
    assert unchanged["published_at"] is None


def test_publish_succeeds_once_the_appeal_reaches_a_terminal_status(api, world):
    """Resolving the appeal both feeds the rate and clears the publication gate.

    PRD 3.9: "`appeal_count` is the number of appeals counted for the variant:
    under `RESTATED` only terminal appeals count, while under `PROVISIONAL` appeals
    still sitting in `SUBMITTED` or `INDEPENDENT_REVIEW` are additionally included
    in `appeal_count` — but never in any rate numerator or denominator, and never
    in the breakdown."

    Design: Difficulty/cross_entity_state_dependency/publish_blocked_by_open_appeal_in_period
    """
    base, scenario, appeal_id, computed = _computed_report_over_an_open_appeal(world)
    assert computed["appeal_count"] == 0
    assert computed["category_rate_breakdown"] == []

    resolved = world.resolve_appeal(
        appeal_id,
        base.senior_id,
        resolution="UPHELD",
        resolution_note="Original call stands",
    )
    assert resolved["status"] == "UPHELD"
    assert resolved["reinstated_content"] is False
    assert_instant_equals(resolved["resolved_at"], "2026-08-01T09:00:00Z", "resolved_at")
    decider = world.get_reviewer(base.frontline_id)
    assert decider["appealed_count"] == 1
    assert decider["upheld_appeal_count"] == 1
    assert_rate_equals(decider["accuracy_score_blended"], 1.0, "accuracy_score_blended")
    assert decider["status"] == "ACTIVE"
    assert_fields(
        world.get_account(base.account_id),
        {"appeal_credits_remaining": 2, "strike_points": 4, "standing": "LIMITED"},
        "account after the upheld appeal",
    )

    recomputed = world.compute_report(computed["id"], variant="RESTATED")
    assert recomputed["enforcement_volume"] == 1
    assert recomputed["appeal_count"] == 1
    assert_rate_equals(recomputed["appeal_overturn_rate"], 0.0, "appeal_overturn_rate")
    assert len(recomputed["category_rate_breakdown"]) == 1
    entry = recomputed["category_rate_breakdown"][0]
    assert entry["category_code"] == base.category_code
    assert entry["appealed"] == 1
    assert entry["overturned"] == 0
    assert_rate_equals(entry["rate"], 0.0, "per-category rate")

    published = validate_success(
        api.publish_transparency_report(computed["id"], headers=ADMIN_HEADERS)
    )
    assert published["status"] == "PUBLISHED"
    assert_instant_equals(published["published_at"], "2026-08-01T09:00:00Z", "published_at")


def test_transparency_appeal_rate_rounds_per_category_before_averaging(api, world):
    """Two categories with different appeal counts expose the round-then-average order.

    PRD 3.9: "Appeal figures are computed by rounding per category **before**
    averaging, and the order is pinned because averaging first and rounding once
    produces a different number."

    Design: Corner/calculations/transparency_appeal_rate_rounds_per_category_before_averaging
    """
    base = build_workforce_baseline(world)
    hate_category = world.create_category(
        code="HATE_SPEECH", name="Hate Speech", severity_tier="T3", specialty="HATE"
    )
    hate_version = world.create_active_version(hate_category["id"], version_label="hv1")
    world.create_queue(
        hate_category["id"], name="EN Hate", language="EN", specialty="HATE"
    )
    hana = world.create_reviewer(
        display_name="Hana Hate",
        role_class="FRONTLINE",
        languages=["EN"],
        specialties=["HATE"],
    )
    world.certify(hana["id"], hate_version["id"])
    world.certify(base.senior_id, hate_version["id"])

    items = [world.create_content(base.account_id, graphic_weight=1) for _ in range(3)]
    signals = [
        world.submit_signal(
            items[0]["id"], policy_category_code=base.category_code, classifier_confidence=0.7
        ),
        world.submit_signal(
            items[1]["id"], policy_category_code=base.category_code, classifier_confidence=0.7
        ),
        world.submit_signal(
            items[2]["id"], policy_category_code="HATE_SPEECH", classifier_confidence=0.7
        ),
    ]
    cases = [world.get_case(signal["resulting_case_id"]) for signal in signals]

    world.assign(cases[0]["id"], target_reviewer_id=base.frontline_id)
    world.decide(cases[0]["id"], base.frontline_id, outcome="REMOVE")
    world.assign(cases[1]["id"], target_reviewer_id=base.frontline_id)
    world.decide(cases[1]["id"], base.frontline_id, outcome="REMOVE")
    world.assign(cases[2]["id"], target_reviewer_id=hana["id"])
    world.decide(cases[2]["id"], hana["id"], outcome="REMOVE")

    appeals = [world.file_appeal(case["id"], base.account_id) for case in cases]
    for appeal in appeals:
        world.route_appeal(appeal["id"], base.auditor_id, target_reviewer_id=base.senior_id)
    world.resolve_appeal(appeals[0]["id"], base.senior_id, resolution="OVERTURNED")
    world.resolve_appeal(appeals[1]["id"], base.senior_id, resolution="UPHELD")
    world.resolve_appeal(appeals[2]["id"], base.senior_id, resolution="OVERTURNED")

    report = world.create_report()
    computed = world.compute_report(report["id"], variant="RESTATED")
    assert computed["status"] == "COMPUTED"
    assert computed["variant"] == "RESTATED"
    assert_rate_equals(computed["appeal_overturn_rate"], 0.75, "appeal_overturn_rate")

    breakdown = computed["category_rate_breakdown"]
    assert [entry["category_code"] for entry in breakdown] == ["HATE_SPEECH", base.category_code]
    assert breakdown[0]["appealed"] == 1
    assert breakdown[0]["overturned"] == 1
    assert_rate_equals(breakdown[0]["rate"], 1.0, "HATE_SPEECH rate")
    assert breakdown[1]["appealed"] == 2
    assert breakdown[1]["overturned"] == 1
    assert_rate_equals(breakdown[1]["rate"], 0.5, "VIOLENT_THREAT rate")

    assert computed["enforcement_volume"] == 1
    assert computed["removal_volume"] == 1
    published = validate_success(
        api.publish_transparency_report(report["id"], headers=ADMIN_HEADERS)
    )
    assert published["status"] == "PUBLISHED"
