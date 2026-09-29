"""
Multi-hop cascades and the two-variant risk score.

Three PRD contracts are pinned here: the four-hop cascade a failed monitoring
visit runs through the vendor, the four-hop cascade a delisted UPC runs through
ceilings, submissions and authorization readiness, and the divergence between the
rolling and the epoch risk score for the same vendor.
"""

from typing import Any, Dict, List

from test_helpers import (
    ANALYST_HEADERS,
    SUPERVISOR_HEADERS,
    ApiClient,
    BlockedReason,
    CeilingStatus,
    EditCode,
    EditResult,
    FoodItemStatus,
    RiskBasis,
    RiskFlag,
    RiskTier,
    StockVerdict,
    SubmissionStatus,
    SupersededReason,
    TrainingType,
    VendorStatus,
    VisitOutcome,
    VisitStatus,
    VisitType,
    VoidedReason,
    assert_adjudicated_total_is_sum_of_allowed,
    assert_claim_line_counts,
    assert_field_values,
    assert_risk_score_components,
    assert_stock_finding,
    assert_vendor,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import MILK_UPC

# --- instants used by these scenarios ---------------------------------------

REAUTH_WINDOW_OPEN_AT = "2029-05-03T00:00:00Z"
SECOND_FAILURE_AT = "2029-05-20T00:00:00Z"
RISK_LIVE_AT = "2026-08-10T00:00:00Z"

# A UPC that is never mapped into the authorized food list.
UNMAPPED_UPC = "00099999999"


# ---------------------------------------------------------------------------
# Private setup helpers - none of the shared fixtures build these exact shapes
# ---------------------------------------------------------------------------


def _start_reauthorization(api: ApiClient, vendor_id: str) -> Dict[str, Any]:
    """Open the reauthorization cycle, moving AUTHORIZED to REAUTH_PENDING."""
    return get_success_data(api.start_reauthorization(vendor_id, None, ANALYST_HEADERS))


def _reauth_pending_vendor_with_one_failure(api: ApiClient) -> Dict[str, Any]:
    """
    A REAUTH_PENDING vendor carrying exactly one uncured finding, plus a second
    routine visit already scheduled but not yet conducted.

    The vendor is authorized at 2026-08-01, so its reauthorization is due
    2029-08-01 and the ninety-day window opens exactly at 2029-05-03.
    """
    fixtures.reset_clock(api)
    bundle = fixtures.authorized_vendor_setup(api)
    vendor_id = bundle["vendor"]["id"]

    fixtures.set_clock(api, REAUTH_WINDOW_OPEN_AT)
    fixtures.record_training(
        api,
        vendor_id,
        completed_at="2029-05-01T00:00:00Z",
        training_type=TrainingType.ANNUAL.value,
    )
    bundle["vendor"] = _start_reauthorization(api, vendor_id)

    first = fixtures.schedule_visit(api, vendor_id, REAUTH_WINDOW_OPEN_AT)
    bundle["visit_one"] = fixtures.conduct_visit(api, first["id"])

    fixtures.set_clock(api, SECOND_FAILURE_AT)
    bundle["visit_two"] = fixtures.schedule_visit(api, vendor_id, SECOND_FAILURE_AT)
    bundle["vendor"] = fixtures.get_vendor(api, vendor_id)
    return bundle


def _delist_cascade_setup(api: ApiClient) -> Dict[str, Any]:
    """
    One AUTHORIZED vendor and one IN_REVIEW vendor, each with an accepted milk
    price in the same closed cycle, and one PROVISIONAL milk ceiling.
    """
    fixtures.reset_clock(api)
    bundle = fixtures.authorized_vendor_setup(api)

    second = fixtures.vendor_in_review(
        api,
        store_name="Bravo Market",
        reported_monthly_redemption_cents=7_000_000,
        training_completed_at="2026-07-20T00:00:00Z",
    )
    submission_two = fixtures.submit_price(
        api, second["id"], bundle["milk_item"]["id"], bundle["cycle"]["id"], 349
    )
    bundle["submission_two"] = fixtures.accept_submission(api, submission_two["id"])
    bundle["close_summary"] = fixtures.close_cycle(api, bundle["cycle"]["id"])

    provisional, _ = fixtures.list_price_ceilings(
        api,
        {
            "food_item_id": bundle["milk_item"]["id"],
            "price_cycle_id": bundle["cycle"]["id"],
            "status": CeilingStatus.PROVISIONAL.value,
            "limit": 100,
        },
    )
    assert len(provisional) == 1, f"expected one provisional ceiling, got {provisional}"
    bundle["provisional_ceiling"] = provisional[0]
    bundle["vendor_two"] = fixtures.get_vendor(api, second["id"])
    return bundle


def _delist_milk(api: ApiClient, food_item_id: str):
    """Delist the milk UPC as a supervisor, supplying the free-text reason."""
    return api.delist_authorized_food_item(
        food_item_id,
        factories.delist_payload(
            delist_reason="Manufacturer discontinued the container size"
        ),
        SUPERVISOR_HEADERS,
    )


def _risk_divergence_lines() -> List[Dict[str, Any]]:
    """
    Five scanned lines against a published milk ceiling of 336 cents: one accepted,
    one reduced by the ceiling, and three rejected by three different edits.
    """
    return [
        factories.claim_line_payload(1, MILK_UPC, 1, 300),
        factories.claim_line_payload(2, MILK_UPC, 2, 400),
        factories.claim_line_payload(3, UNMAPPED_UPC, 1, 250),
        factories.claim_line_payload(4, MILK_UPC, 9, 300),
        factories.claim_line_payload(5, MILK_UPC, 0, 300),
    ]


def _risk_divergence_setup(api: ApiClient) -> Dict[str, Any]:
    """
    A vendor whose risk epoch was frozen at 2026-08-01, before the failed visit
    and the adjudicated claim that the live window now counts.
    """
    fixtures.reset_clock(api)
    bundle = fixtures.published_ceiling_setup(api)
    bundle["risk_run"] = fixtures.run_risk_run(api)

    fixtures.set_clock(api, RISK_LIVE_AT)
    vendor_id = bundle["vendor"]["id"]
    visit = fixtures.schedule_visit(api, vendor_id, RISK_LIVE_AT)
    bundle["visit"] = fixtures.conduct_visit(api, visit["id"])

    claim = fixtures.file_claim(
        api, vendor_id, _risk_divergence_lines(), claim_month="2026-07"
    )
    bundle["claim"] = fixtures.adjudicate(api, claim["id"])
    bundle["claim_lines"] = fixtures.claim_lines_of(api, claim["id"])
    bundle["vendor"] = fixtures.get_vendor(api, vendor_id)
    return bundle


# ---------------------------------------------------------------------------
# The failed-visit cascade
# ---------------------------------------------------------------------------


def test_second_failed_visit_records_the_finding_and_opens_the_cure_window(api):
    """
    The second failed visit stamps its verdicts and raises the finding count to two.

    "A visit whose outcome is any of the three failure values moves `SCHEDULED → FAILED` and triggers a four-hop cascade, where each hop fires only because the previous one changed something."
    "**Hop 1** always runs: `conducted_at`, the `outcome`, the `stock_findings` verdicts, `stock_compliance_pct`, and `overcharge_cents` are stamped; the vendor's `open_finding_count` rises by one; and the vendor's `cure_deadline_at` is set to thirty days after the logical clock, opening the cure window."
    "The first failing visit of an otherwise clean vendor therefore stops after hop 1: one finding is recorded, a cure deadline is set, and nothing else moves."
    "For each participating category, the requirement is the category's `min_stock_units` multiplied by that multiplier and rounded **up** to a whole number, and that figure is stamped onto the finding as `required_units`."
    "The category's verdict is then decided by the first of these tests that applies: if no observation was recorded for the category at all, the verdict is `MISSING` and the server creates the finding entry itself with `observed_units` 0 and `observed_variety_count` 0; otherwise, if `observed_units` is strictly less than `required_units`, the verdict is `BELOW_UNITS`; otherwise, if `observed_variety_count` is strictly less than the category's `min_variety_count`, the verdict is `BELOW_VARIETY`; otherwise the verdict is `PASS` and the category counts as passing."
    "The `stock_compliance_pct` is then 100 multiplied by the number of passing categories divided by the number of participating categories, rounded half up to one decimal place; when no category participates at all, the figure is exactly 100.0."
    "If any participating category came out `MISSING`, the outcome is `FAIL_MISSING_CATEGORY`."

    Design: Difficulty/transitive_cascade/visit_failure_cascades_to_compliance_buy_and_reauth_hold
    """
    bundle = _reauth_pending_vendor_with_one_failure(api)

    # One failure alone does not cross the two-finding threshold.
    assert_vendor(
        bundle["vendor"],
        open_finding_count=1,
        compliance_buy_required=False,
        reauthorization_hold=False,
        reauth_blocked_reason=None,
        risk_flag=RiskFlag.NONE.value,
    )

    visit = validate_success(
        api.conduct_visit(
            bundle["visit_two"]["id"], factories.conduct_payload(), ANALYST_HEADERS
        )
    )

    assert_field_values(
        visit,
        status=VisitStatus.FAILED.value,
        outcome=VisitOutcome.FAIL_MISSING_CATEGORY.value,
        stock_compliance_pct=0.0,  # 100 x 0 passing / 1 participating category
        overcharge_cents=0,
        conducted_at="2029-05-20T00:00:00.000Z",
    )
    assert len(visit["stock_findings"]) == 1, (
        f"only the one stock_required category participates, got {visit['stock_findings']}"
    )
    assert_stock_finding(
        visit,
        bundle["milk_category"]["id"],
        required_units=6,  # ceil(4 x 1.5) = 6 required units
        verdict=StockVerdict.MISSING.value,
        observed_units=0,
        observed_variety_count=0,
    )

    vendor = fixtures.get_vendor(api, bundle["vendor"]["id"])
    assert_vendor(
        vendor,
        open_finding_count=2,
        # 2029-05-20 plus 30 days opens the cure window on 2029-06-19
        cure_deadline_at="2029-06-19T00:00:00.000Z",
    )


def test_second_finding_flips_the_compliance_buy_flag_and_books_the_buy(api):
    """
    Reaching two uncured findings flips the flag, and that flip manufactures a
    system-created compliance buy fourteen days out.

    "**Hop 2** fires only when `open_finding_count` has thereby reached two uncured findings: the vendor's `compliance_buy_required` flips to true and its `risk_flag` becomes `HIGH_FINDING_COUNT`."
    "**Hop 3** fires only because hop 2 flipped `compliance_buy_required` to true: the system creates a MonitoringVisit of its own for the same vendor with `visit_type` `COMPLIANCE_BUY`, `status` `SCHEDULED`, `auto_generated` true, and `scheduled_for` set to fourteen days after the logical clock."
    "Being system-created, this visit is exempt from the seven-day blackout rule and may land inside another visit's buffer."
    "It is the second uncured failure that manufactures the compliance buy and the reauthorization hold."

    Design: Difficulty/transitive_cascade/visit_failure_cascades_to_compliance_buy_and_reauth_hold
    """
    bundle = _reauth_pending_vendor_with_one_failure(api)

    validate_success(
        api.conduct_visit(
            bundle["visit_two"]["id"], factories.conduct_payload(), ANALYST_HEADERS
        )
    )

    vendor = fixtures.get_vendor(api, bundle["vendor"]["id"])
    assert_vendor(
        vendor,
        compliance_buy_required=True,
        risk_flag=RiskFlag.HIGH_FINDING_COUNT.value,
    )

    rows, meta = validate_paginated(
        api.list_monitoring_visits(
            SUPERVISOR_HEADERS,
            {
                "vendor_id": vendor["id"],
                "visit_type": VisitType.COMPLIANCE_BUY.value,
                "status": VisitStatus.SCHEDULED.value,
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 1, f"expected exactly one booked compliance buy, got {rows}"
    assert_field_values(
        rows[0],
        vendor_id=vendor["id"],
        visit_type=VisitType.COMPLIANCE_BUY.value,
        status=VisitStatus.SCHEDULED.value,
        auto_generated=True,
        outcome=VisitOutcome.PENDING.value,
        # fourteen days after the logical clock of 2029-05-20
        scheduled_for="2029-06-03T00:00:00.000Z",
    )


def test_booked_compliance_buy_holds_reauthorization_and_blocks_its_completion(api):
    """
    The booked compliance buy raises the hold, and the hold refuses the completion
    of the reauthorization cycle.

    "**Hop 4** fires only because a `SCHEDULED` `COMPLIANCE_BUY` visit now exists: the vendor's `reauthorization_hold` flips to true, and if the vendor happens to be `REAUTH_PENDING` at that moment, its `reauth_blocked_reason` is stamped `PENDING_COMPLIANCE_BUY`."
    "The vendor must be `REAUTH_PENDING`; its training must be current, or `ERR_VENDOR_TRAINING_EXPIRED`; no case of the vendor may be `OPENED` or `NOTICE_SERVED`, or `ERR_OPEN_SANCTION_CASE_EXISTS`; `reauthorization_hold` must be false, or `ERR_REAUTHORIZATION_HOLD`; the peer group must be `ACTIVE`, or `ERR_PEER_GROUP_RETIRED`; and `price_submission_complete` must be true against the current cycle, or `ERR_PRICE_SUBMISSIONS_INCOMPLETE`."
    "On success, `reauthorization_due_at` is advanced by thirty-six calendar months **from its own previous value**, never from the logical clock, so that a vendor completing late does not gain extra time and cycles never drift; `reauth_completed_count` rises by one; and `reauth_blocked_reason` is cleared to null."
    "It walks every non-terminal vendor in ascending `created_at` order, refreshing each vendor's `risk_score`, `risk_tier`, and `risk_epoch_at` from the epoch variant."

    Design: Difficulty/transitive_cascade/visit_failure_cascades_to_compliance_buy_and_reauth_hold
    """
    bundle = _reauth_pending_vendor_with_one_failure(api)
    vendor_id = bundle["vendor"]["id"]

    validate_success(
        api.conduct_visit(
            bundle["visit_two"]["id"], factories.conduct_payload(), ANALYST_HEADERS
        )
    )

    held = fixtures.get_vendor(api, vendor_id)
    assert_vendor(
        held,
        reauthorization_hold=True,
        reauth_blocked_reason=BlockedReason.PENDING_COMPLIANCE_BUY.value,
        authorization_status=VendorStatus.REAUTH_PENDING.value,
    )

    validate_error(
        api.complete_reauthorization(vendor_id, None, SUPERVISOR_HEADERS),
        "ERR_REAUTHORIZATION_HOLD",
    )

    after = fixtures.get_vendor(api, vendor_id)
    assert_vendor(
        after,
        authorization_status=VendorStatus.REAUTH_PENDING.value,
        reauth_completed_count=0,
        # authorized at 2026-08-01 plus thirty-six calendar months, untouched by
        # the refused completion
        reauthorization_due_at="2029-08-01T00:00:00.000Z",
        # the cascade sets flags; only the risk run refreshes the persisted score
        risk_score=0.0,
        risk_tier=RiskTier.LOW.value,
        risk_epoch_at=None,
    )


# ---------------------------------------------------------------------------
# The item-delisting cascade
# ---------------------------------------------------------------------------


def test_delisting_a_upc_supersedes_its_ceilings(api):
    """
    Delisting stamps the item and supersedes every ceiling that priced it.

    "Delisting a UPC is the most far-reaching configuration action in the system, and it runs as a four-hop cascade driven by a `VendorUnitSupervisor` who supplies a free-text `delist_reason`."
    "In the first hop, the item's `status` becomes `DELISTED` while `delisted_at` takes the logical clock and `delist_reason` is stored."
    "In the second hop, because the item is no longer authorized, every PriceCeiling for that item whose `status` is `PROVISIONAL` or `ACTIVE` moves to `SUPERSEDED` with `superseded_reason` `ITEM_DELISTED`."

    Design: Difficulty/transitive_cascade/item_delist_cascades_to_ceilings_submissions_and_authorization_block
    """
    bundle = _delist_cascade_setup(api)

    item = validate_success(_delist_milk(api, bundle["milk_item"]["id"]))

    assert_field_values(
        item,
        status=FoodItemStatus.DELISTED.value,
        delisted_at="2026-08-01T00:00:00.000Z",
        delist_reason="Manufacturer discontinued the container size",
    )

    still_provisional, meta = fixtures.list_price_ceilings(
        api,
        {
            "food_item_id": bundle["milk_item"]["id"],
            "price_cycle_id": bundle["cycle"]["id"],
            "status": CeilingStatus.PROVISIONAL.value,
            "limit": 100,
        },
    )
    assert meta["total_count"] == 0, (
        f"no ceiling of a delisted item may remain PROVISIONAL, got {still_provisional}"
    )

    superseded = fixtures.get_price_ceiling(api, bundle["provisional_ceiling"]["id"])
    assert_field_values(
        superseded,
        status=CeilingStatus.SUPERSEDED.value,
        superseded_reason=SupersededReason.ITEM_DELISTED.value,
    )


def test_delisting_voids_the_submissions_that_fed_the_ceiling(api):
    """
    With no ceiling left, the accepted shelf prices are voided and every affected
    vendor loses its submission readiness.

    "In the third hop, because no ceiling remains to serve as an adjudication basis, every PriceSubmission for that item whose `status` is `SUBMITTED` or `ACCEPTED`, and whose price cycle is itself `OPEN` or `CLOSED`, moves to `VOIDED` with `voided_reason` `ITEM_DELISTED` — submissions belonging to a `PUBLISHED` cycle are left alone, because that cycle's history is closed."
    "In the fourth hop, because those submissions were voided, each affected vendor's `accepted_submission_count` is decremented and its `price_submission_complete` is recomputed, turning false when the delisted item had `required_for_authorization` set to true."

    Design: Difficulty/transitive_cascade/item_delist_cascades_to_ceilings_submissions_and_authorization_block
    """
    bundle = _delist_cascade_setup(api)

    validate_success(_delist_milk(api, bundle["milk_item"]["id"]))

    for submission in (bundle["submission"], bundle["submission_two"]):
        voided = fixtures.get_price_submission(api, submission["id"])
        assert_field_values(
            voided,
            status=SubmissionStatus.VOIDED.value,
            voided_reason=VoidedReason.ITEM_DELISTED.value,
        )

    for vendor_key in ("vendor", "vendor_two"):
        vendor = fixtures.get_vendor(api, bundle[vendor_key]["id"])
        assert_vendor(
            vendor,
            accepted_submission_count=0,  # the single accepted milk price was voided
            price_submission_complete=False,
        )


def test_delisting_blocks_a_pending_authorization_without_de_authorizing_anyone(api):
    """
    The lost readiness refuses the vendor still under review while leaving the
    already-authorized vendor and the membership headcount alone.

    "On `POST /vendors/{id}/authorize` and `POST /vendors/{id}/complete-reauthorization`, `price_submission_complete` is true — otherwise `ERR_PRICE_SUBMISSIONS_INCOMPLETE`."
    "And `price_submission_complete` must be true, or `ERR_PRICE_SUBMISSIONS_INCOMPLETE`."
    "A peer group's `member_count` is the number of vendors assigned to it whose `authorization_status` is `AUTHORIZED`, `REAUTH_PENDING`, or `SUSPENDED`."
    "Vendors in `APPLICANT`, `IN_REVIEW`, `DENIED`, or `DISQUALIFIED` are not counted, and vendors with no peer group assigned are not counted at all."

    Design: Difficulty/transitive_cascade/item_delist_cascades_to_ceilings_submissions_and_authorization_block
    """
    bundle = _delist_cascade_setup(api)

    validate_success(_delist_milk(api, bundle["milk_item"]["id"]))

    validate_error(
        api.authorize_vendor(bundle["vendor_two"]["id"], None, SUPERVISOR_HEADERS),
        "ERR_PRICE_SUBMISSIONS_INCOMPLETE",
    )

    blocked = fixtures.get_vendor(api, bundle["vendor_two"]["id"])
    assert_vendor(
        blocked,
        authorization_status=VendorStatus.IN_REVIEW.value,
        authorized_at=None,
    )

    kept = fixtures.get_vendor(api, bundle["vendor"]["id"])
    assert_vendor(kept, authorization_status=VendorStatus.AUTHORIZED.value)

    peer_group = fixtures.get_peer_group(api, bundle["peer_group"]["id"])
    # only the AUTHORIZED vendor counts; the one still IN_REVIEW never did
    assert_field_values(peer_group, member_count=1)


# ---------------------------------------------------------------------------
# The rolling and epoch risk score
# ---------------------------------------------------------------------------


def test_rolling_risk_profile_scores_the_live_window(api):
    """
    The rolling basis evaluates the 180-day window against the logical clock and
    weights the three component percentages into the score.

    "The score is evaluated over a window ending at a variant-supplied instant and beginning 180 days earlier."
    "Within that window, the claim lines considered are those belonging to the vendor's RedemptionClaims whose `status` is `ADJUDICATED`, `ADJUSTED`, or `PAID` and whose claim's `adjudicated_at` falls after the window start and at or before the window end."
    "From those lines, `edit_rejection_rate_pct` is 100 multiplied by the number of lines whose `edit_result` is `REJECTED` divided by the total number of lines considered, and `price_excess_pct` is 100 multiplied by the number of lines whose `edit_code` is `E05` divided by that same total; when no lines fall in the window, both figures are 0."
    "The visits considered are the vendor's MonitoringVisits whose `status` is `PASSED`, `FAILED`, `CURED`, or `ESCALATED` and whose `conducted_at` falls in the same window, and `failed_visit_pct` is 100 multiplied by the number of those whose `status` is `FAILED` or `ESCALATED` divided by the number considered; with no visits in the window the figure is 0."
    "The weighted sum takes 0.40 of `edit_rejection_rate_pct`, plus 0.25 of `price_excess_pct`, plus 0.20 of `failed_visit_pct`, plus 15.0 for each of the vendor's `sanction_points` counted up to a cap of two points — so a vendor with three or more points contributes exactly 30.0 from that term, and a vendor with one point contributes 15.0."
    "The `risk_tier` is then read off the rounded score: `HIGH` when the score is at least 60.0, `ELEVATED` when it is at least 30.0 but below 60.0, and `LOW` below 30.0."
    "The **rolling** variant is a computed read available to analysts, supervisors, and investigators; a `basis` query parameter of `ROLLING`, or an omitted `basis`, evaluates the window against the logical clock at request time, so a claim adjudicated one second ago is already counted, and nothing is persisted."
    "The response reports the `vendor_id`, the `basis` used, the `window_start` and `window_end` instants, the `evaluated_line_count` and `evaluated_visit_count` that fell in the window, the three component percentages `edit_rejection_rate_pct`, `price_excess_pct`, and `failed_visit_pct`, the vendor's `sanction_points`, and the resulting `risk_score` and `risk_tier`."
    "**`E01`** — the UPC did not resolve to any authorized food item, or the resolved item's `status` is `DELISTED`."
    "**`E03`** — the quantity is out of range: `quantity` is zero or negative, or it exceeds the category's `max_units_per_transaction`."
    "If the line's `charged_unit_price_cents` is strictly greater than that ceiling, the line's `edit_result` becomes `ACCEPTED_REDUCED` with `edit_code` `E05`, and its `allowed_cents` is the ceiling's `mar_cents` multiplied by `quantity` — the vendor is paid at the ceiling, not at what it charged."
    "If the charged price equals or falls below the ceiling, the line's `edit_result` is `ACCEPTED`, its `edit_code` stays null, and its `allowed_cents` is `charged_unit_price_cents` multiplied by `quantity`."
    "Note that `applied_mar_cents` is set only when a ceiling was actually consulted; a line rejected by `E01`, `E02`, `E03`, or `E04` leaves it null."
    "When the peer count falls short, `basis` is `STATEWIDE_FALLBACK` and the candidate set is rebuilt with the identical filter but **without** the peer-group restriction, restricted to submissions from vendors whose own peer group has `status` `ACTIVE`; that broader list is likewise sorted ascending by price with the `created_at` tie-break."
    "Under `PEER_MEDIAN`, the base is the median: for a candidate set of odd size it is the single middle element, and for an even size it is the mean of the two middle elements."
    "The allowance is applied first: the base is multiplied by one plus the peer group's `competitive_allowance_pct`, giving an allowance-adjusted figure."
    "The statewide cap is computed second, as 1.25 times the smallest price in the **same** candidate set that produced the base — not the smallest peer price when the fallback was used, and not a statewide minimum computed separately."
    "Rounding happens once, at the very end: `mar_cents` is the lesser of the allowance-adjusted figure and the cap, rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/risk_score_rolling_vs_epoch_diverges_on_vendor
    """
    bundle = _risk_divergence_setup(api)
    lines = bundle["claim_lines"]

    # The one accepted milk price of 320 is the only candidate, so the peer count of
    # one falls short of min_submissions_for_ceiling 3 and the statewide fallback
    # rebuilds the same single-element set: median 320, times 1.05 gives 336.0, and
    # the cap of 1.25 x 320 = 400.0 does not bind, so mar_cents is 336.
    assert_field_values(
        lines[0],
        edit_result=EditResult.ACCEPTED.value,
        edit_code=None,
        applied_mar_cents=336,
        allowed_cents=300,  # 300 charged is at or below the ceiling, so 1 x 300
    )
    assert_field_values(
        lines[1],
        edit_result=EditResult.ACCEPTED_REDUCED.value,
        edit_code=EditCode.E05.value,
        applied_mar_cents=336,
        allowed_cents=672,  # 336 x 2 containers, paid at the ceiling not at 400
    )
    assert_field_values(
        lines[2],
        edit_result=EditResult.REJECTED.value,
        edit_code=EditCode.E01.value,
        food_item_id=None,
        applied_mar_cents=None,  # no ceiling was consulted
        allowed_cents=0,
    )
    assert_field_values(
        lines[3],
        edit_result=EditResult.REJECTED.value,
        edit_code=EditCode.E03.value,  # 9 exceeds max_units_per_transaction 6
        applied_mar_cents=None,
        allowed_cents=0,
    )
    assert_field_values(
        lines[4],
        edit_result=EditResult.REJECTED.value,
        edit_code=EditCode.E03.value,  # quantity zero
        applied_mar_cents=None,
        allowed_cents=0,
    )

    profile = validate_success(
        api.get_vendor_risk_profile(
            bundle["vendor"]["id"],
            SUPERVISOR_HEADERS,
            {"basis": RiskBasis.ROLLING.value},
        )
    )

    assert_field_values(
        profile,
        vendor_id=bundle["vendor"]["id"],
        basis=RiskBasis.ROLLING.value,
        evaluated_line_count=5,
        evaluated_visit_count=1,
        # 2026-08-10 back 180 days
        window_start="2026-02-11T00:00:00.000Z",
        window_end="2026-08-10T00:00:00.000Z",
    )
    assert_risk_score_components(
        profile,
        edit_rejection_rate_pct=60.0,  # 100 x 3 rejected / 5 lines
        price_excess_pct=20.0,  # 100 x 1 E05 line / 5 lines
        failed_visit_pct=100.0,  # 100 x 1 failed / 1 conducted visit
        sanction_points=0,
        # 0.40 x 60.0 + 0.25 x 20.0 + 0.20 x 100.0 = 49.0
        expected_score=49.0,
        expected_tier=RiskTier.ELEVATED.value,
    )


def test_epoch_risk_profile_replays_the_frozen_snapshot(api):
    """
    The epoch basis evaluates the window against the vendor's risk_epoch_at, so
    records created after the last run are invisible to it.

    "The **epoch** variant is the persisted snapshot: a `basis` of `EPOCH` replays whatever the last risk run computed, evaluating the window against the vendor's `risk_epoch_at`."
    "Records created after that run are invisible to the vendor's stored `risk_score` and `risk_tier` until the next run, so the persisted tier — the one that gates compliance-buy eligibility — can lag the rolling tier by a whole epoch."
    "The score is evaluated over a window ending at a variant-supplied instant and beginning 180 days earlier."
    "From those lines, `edit_rejection_rate_pct` is 100 multiplied by the number of lines whose `edit_result` is `REJECTED` divided by the total number of lines considered, and `price_excess_pct` is 100 multiplied by the number of lines whose `edit_code` is `E05` divided by that same total; when no lines fall in the window, both figures are 0."
    "The visits considered are the vendor's MonitoringVisits whose `status` is `PASSED`, `FAILED`, `CURED`, or `ESCALATED` and whose `conducted_at` falls in the same window, and `failed_visit_pct` is 100 multiplied by the number of those whose `status` is `FAILED` or `ESCALATED` divided by the number considered; with no visits in the window the figure is 0."
    "The `risk_tier` is then read off the rounded score: `HIGH` when the score is at least 60.0, `ELEVATED` when it is at least 30.0 but below 60.0, and `LOW` below 30.0."

    Design: Difficulty/dual_variant_calc/risk_score_rolling_vs_epoch_diverges_on_vendor
    """
    bundle = _risk_divergence_setup(api)

    profile = validate_success(
        api.get_vendor_risk_profile(
            bundle["vendor"]["id"],
            SUPERVISOR_HEADERS,
            {"basis": RiskBasis.EPOCH.value},
        )
    )

    assert_field_values(
        profile,
        vendor_id=bundle["vendor"]["id"],
        basis=RiskBasis.EPOCH.value,
        # the window ends at the epoch the run froze, before the visit and the claim
        window_end="2026-08-01T00:00:00.000Z",
        window_start="2026-02-02T00:00:00.000Z",  # 2026-08-01 back 180 days
        evaluated_line_count=0,
        evaluated_visit_count=0,
    )
    assert_risk_score_components(
        profile,
        edit_rejection_rate_pct=0.0,
        price_excess_pct=0.0,
        failed_visit_pct=0.0,
        sanction_points=0,
        # 0.40 x 0.0 + 0.25 x 0.0 + 0.20 x 0.0 + 0 points = 0.0
        expected_score=0.0,
        expected_tier=RiskTier.LOW.value,
    )


def test_persisted_risk_tier_lags_the_rolling_tier_by_one_epoch(api):
    """
    The gating tier stored on the vendor stays at the last run's figures while the
    live read already reports the higher tier.

    "Advancing the epoch is a `SystemOperator` capability."
    "It walks every non-terminal vendor in ascending `created_at` order, refreshing each vendor's `risk_score`, `risk_tier`, and `risk_epoch_at` from the epoch variant."
    "A vendor whose refreshed `risk_tier` comes out `HIGH` has its `risk_flag` set to `HIGH_SCORE` and its `compliance_buy_required` set to true — the second, score-driven route to a compliance buy alongside the finding-count route of §3.6."
    "The run reports the `epoch_at` instant it used, the `evaluated_vendor_count`, the `high_risk_vendor_count`, the `escalated_visit_count`, and the `opened_sanction_case_count`."
    "Records created after that run are invisible to the vendor's stored `risk_score` and `risk_tier` until the next run, so the persisted tier — the one that gates compliance-buy eligibility — can lag the rolling tier by a whole epoch."
    "At creation the claim's `status` is `SUBMITTED`, its `line_count` is the number of lines created, and its `submitted_total_cents` is the sum over lines of `quantity` multiplied by `charged_unit_price_cents`."
    "`adjudicated_total_cents` is the sum of `allowed_cents` over all lines."
    "`accepted_line_count`, `reduced_line_count`, and `rejected_line_count` count the lines whose `edit_result` is `ACCEPTED`, `ACCEPTED_REDUCED`, and `REJECTED` respectively, over every line regardless of outcome."
    "**`E01`** — the UPC did not resolve to any authorized food item, or the resolved item's `status` is `DELISTED`."
    "**`E03`** — the quantity is out of range: `quantity` is zero or negative, or it exceeds the category's `max_units_per_transaction`."

    Design: Difficulty/dual_variant_calc/risk_score_rolling_vs_epoch_diverges_on_vendor
    """
    bundle = _risk_divergence_setup(api)

    assert_field_values(
        bundle["risk_run"],
        epoch_at="2026-08-01T00:00:00.000Z",
        evaluated_vendor_count=1,
        high_risk_vendor_count=0,
        escalated_visit_count=0,
        opened_sanction_case_count=0,
    )

    # The records the live window counts, and the epoch window does not.
    assert_field_values(
        bundle["claim"],
        line_count=5,
        # 1x300 + 2x400 + 1x250 + 9x300 + 0x300 = 4050
        submitted_total_cents=4050,
        # the unmapped UPC fails E01, quantity 9 and quantity 0 each fail E03
        rejected_line_count=3,
    )
    assert_claim_line_counts(bundle["claim"], bundle["claim_lines"])
    assert_adjudicated_total_is_sum_of_allowed(bundle["claim"], bundle["claim_lines"])
    assert_field_values(
        bundle["visit"],
        status=VisitStatus.FAILED.value,
        outcome=VisitOutcome.FAIL_MISSING_CATEGORY.value,
        stock_compliance_pct=0.0,
    )

    assert_vendor(
        bundle["vendor"],
        risk_score=0.0,
        risk_tier=RiskTier.LOW.value,
        risk_epoch_at="2026-08-01T00:00:00.000Z",
        # a refresh that came out LOW sets neither score-driven consequence
        risk_flag=RiskFlag.NONE.value,
        compliance_buy_required=False,
    )

    rolling = validate_success(
        api.get_vendor_risk_profile(
            bundle["vendor"]["id"],
            SUPERVISOR_HEADERS,
            {"basis": RiskBasis.ROLLING.value},
        )
    )
    assert_field_values(
        rolling,
        risk_score=49.0,
        risk_tier=RiskTier.ELEVATED.value,
    )
    assert rolling["risk_score"] != bundle["vendor"]["risk_score"], (
        "the live read and the persisted snapshot must diverge across the epoch"
    )
