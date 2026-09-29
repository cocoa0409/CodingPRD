"""
Price submission collision and window boundaries, the visit rejection ladder, the
inline publication summary, and the immediacy of derived state on authorization.

Every test builds its own world from scratch through the documented endpoints,
because the server is relaunched against an empty database before each one.
"""

from test_helpers import (
    ANALYST_HEADERS,
    SUPERVISOR_HEADERS,
    ApiErrorId,
    assert_ceiling_derivation,
    assert_field_values,
    factories,
    fixtures,
    make_vendor_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.types import (
    CeilingBasis,
    CeilingStatus,
    MarMethod,
    PriceCycleStatus,
    ReviewReason,
    StoreType,
    SubmissionStatus,
    SupersededReason,
    VendorStatus,
    VisitType,
)


def test_duplicate_price_submission_for_same_vendor_item_cycle_rejected(api):
    """
    A live submission for the same vendor, item and cycle blocks another, and a rejected
    submission still counts as live while another vendor is unaffected.

    "And no other submission may already exist for the same combination of vendor, food item, and cycle in `status` `SUBMITTED`, `ACCEPTED`, or `REJECTED`; a previously `VOIDED` submission does not block a fresh one, and a live collision is refused with `ERR_DUPLICATE_PRICE_SUBMISSION`."
    "A decision of `REJECT` moves it `SUBMITTED → REJECTED` and requires a `review_reason` in the body, one of `PRICE_IMPLAUSIBLE`, `MISSING_DOCUMENTATION`, or `ABOVE_STATEWIDE_OUTLIER`; a rejection with no reason supplied is refused with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/duplicate_price_submission_for_same_vendor_item_cycle_rejected
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    milk_category = fixtures.create_food_category(api)
    milk_item = fixtures.create_food_item(api, milk_category["id"])
    cycle_q3 = fixtures.create_price_cycle(api)  # [2026-08-01, 2026-09-01)
    cycle_q4 = fixtures.create_price_cycle(
        api,
        cycle_code="2026Q4",
        submission_open_at="2026-09-01T00:00:00Z",
        submission_due_at="2026-10-01T00:00:00Z",
    )
    vendor_one = fixtures.create_vendor(api, store_name="Alpha Market")
    vendor_two = fixtures.create_vendor(api, store_name="Beta Market")
    headers_one = make_vendor_operator_headers(vendor_one["id"])
    headers_two = make_vendor_operator_headers(vendor_two["id"])

    first = validate_success(
        api.create_price_submission(
            factories.price_submission_payload(
                vendor_one["id"], milk_item["id"], cycle_q3["id"], 320
            ),
            headers_one,
        ),
        201,
    )
    assert_field_values(first, status=SubmissionStatus.SUBMITTED.value)

    # A SUBMITTED row for the same triple blocks a second attempt.
    validate_error(
        api.create_price_submission(
            factories.price_submission_payload(
                vendor_one["id"], milk_item["id"], cycle_q3["id"], 330
            ),
            headers_one,
        ),
        ApiErrorId.DUPLICATE_PRICE_SUBMISSION.value,
    )

    rejected = fixtures.reject_submission(
        api, first["id"], review_reason=ReviewReason.PRICE_IMPLAUSIBLE.value
    )
    assert_field_values(rejected, status=SubmissionStatus.REJECTED.value)

    # REJECTED is inside the blocking set, so the triple is still taken.
    validate_error(
        api.create_price_submission(
            factories.price_submission_payload(
                vendor_one["id"], milk_item["id"], cycle_q3["id"], 340
            ),
            headers_one,
        ),
        ApiErrorId.DUPLICATE_PRICE_SUBMISSION.value,
    )

    # The collision is scoped to the vendor, so a different vendor may submit.
    other = validate_success(
        api.create_price_submission(
            factories.price_submission_payload(
                vendor_two["id"], milk_item["id"], cycle_q3["id"], 320
            ),
            headers_two,
        ),
        201,
    )
    assert_field_values(
        other, vendor_id=vendor_two["id"], status=SubmissionStatus.SUBMITTED.value
    )

    _, meta_q3 = validate_paginated(
        api.list_price_submissions(
            SUPERVISOR_HEADERS,
            {
                "vendor_id": vendor_one["id"],
                "price_cycle_id": cycle_q3["id"],
                "limit": 100,
            },
        )
    )
    assert meta_q3["total_count"] == 1, (
        f"only the one rejected submission should exist for this vendor: {meta_q3}"
    )
    _, meta_q4 = validate_paginated(
        api.list_price_submissions(
            SUPERVISOR_HEADERS,
            {
                "vendor_id": vendor_one["id"],
                "price_cycle_id": cycle_q4["id"],
                "limit": 100,
            },
        )
    )
    assert meta_q4["total_count"] == 0, (
        f"the collision must not have written anything into the later cycle: {meta_q4}"
    )


def test_visit_scheduled_in_the_past_rejected_before_blackout_conflict(api):
    """
    A visit dated before the logical clock is refused for the past date even when it also
    lands inside another visit's blackout buffer, because the lower-numbered rule wins.

    "When a request violates more than one rule, exactly one error is returned: the one belonging to the lowest-numbered rule in the ladder below."
    "On `POST /monitoring-visits`, `scheduled_for` is not earlier than the logical clock — otherwise `ERR_VISIT_DATE_IN_PAST` (HTTP 422)."
    "On `POST /monitoring-visits`, the blackout buffer around `scheduled_for` is clear — otherwise `ERR_VISIT_BLACKOUT_CONFLICT`."
    "Finally, a blackout buffer keeps visits from clustering: if any other visit of the same vendor is still `SCHEDULED` and the gap between its `scheduled_for` and the new one is seven days or less in either direction, the new visit is refused with `ERR_VISIT_BLACKOUT_CONFLICT`."
    "The buffer is a closed symmetric window, so a gap of exactly seven days conflicts and a gap of eight days does not."

    Design: Corner/validations/visit_scheduled_in_the_past_rejected_before_blackout_conflict
    """
    bundle = fixtures.authorized_vendor_setup(api)
    vendor_id = bundle["vendor"]["id"]

    fixtures.set_clock(api, "2026-08-10T00:00:00Z")
    anchor = fixtures.schedule_visit(api, vendor_id, "2026-08-12T00:00:00Z")
    assert_field_values(anchor, scheduled_for="2026-08-12T00:00:00.000Z")

    # 2026-08-08 is two days before the clock and four days from the anchor, so both the
    # past-date rule and the blackout rule are violated; the past-date rule is lower.
    validate_error(
        api.create_monitoring_visit(
            factories.monitoring_visit_payload(
                vendor_id,
                visit_type=VisitType.ROUTINE.value,
                scheduled_for="2026-08-08T00:00:00Z",
            ),
            ANALYST_HEADERS,
        ),
        ApiErrorId.VISIT_DATE_IN_PAST.value,
    )

    # 2026-08-14 is in the future, so only the blackout rule can fire: the gap to the
    # anchor is two days, well inside the closed seven-day window.
    validate_error(
        api.create_monitoring_visit(
            factories.monitoring_visit_payload(
                vendor_id,
                visit_type=VisitType.ROUTINE.value,
                scheduled_for="2026-08-14T00:00:00Z",
            ),
            ANALYST_HEADERS,
        ),
        ApiErrorId.VISIT_BLACKOUT_CONFLICT.value,
    )

    visits, meta = validate_paginated(
        api.list_monitoring_visits(
            ANALYST_HEADERS, {"vendor_id": vendor_id, "limit": 100}
        )
    )
    assert meta["total_count"] == 1, f"neither refusal may have persisted a visit: {meta}"
    assert_field_values(visits[0], id=anchor["id"])


def test_submission_window_half_open_boundary_rejects_at_due_instant(api):
    """
    The collection window includes its opening instant and excludes its due instant, so a
    submission at the due instant is refused while the cycle itself is still open.

    "A `VendorUnitSupervisor` opens a cycle with a `cycle_code` unique across all cycles and a **half-open** collection window running from `submission_open_at` inclusive to `submission_due_at` exclusive."
    "The cycle must be `OPEN` and the logical clock must fall inside the half-open window — at or after `submission_open_at` and strictly before `submission_due_at` — or the request is refused with `ERR_SUBMISSION_WINDOW_CLOSED`."
    "Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server never falls back to real time."

    Design: Corner/validations/submission_window_half_open_boundary_rejects_at_due_instant
    """
    milk_category = fixtures.create_food_category(api)
    milk_item = fixtures.create_food_item(api, milk_category["id"])
    juice_item = fixtures.create_food_item(
        api,
        milk_category["id"],
        upc=fixtures.JUICE_UPC,
        brand="Statewide Juice",
        container_size_oz=64,
        required_for_authorization=False,
    )
    cereal_item = fixtures.create_food_item(
        api,
        milk_category["id"],
        upc=fixtures.BREAD_UPC,
        brand="Statewide Grain",
        container_size_oz=18,
        required_for_authorization=False,
    )
    # The window is [2026-08-01T00:00:00Z, 2026-09-01T00:00:00Z).
    cycle = fixtures.create_price_cycle(api)
    vendor = fixtures.create_vendor(api)
    vendor_headers = make_vendor_operator_headers(vendor["id"])

    # One millisecond before the opening instant is outside the window.
    fixtures.set_clock(api, "2026-07-31T23:59:59.999Z")
    validate_error(
        api.create_price_submission(
            factories.price_submission_payload(
                vendor["id"], milk_item["id"], cycle["id"], 320
            ),
            vendor_headers,
        ),
        ApiErrorId.SUBMISSION_WINDOW_CLOSED.value,
    )

    # The opening instant itself is inside, because the lower bound is inclusive.
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    validate_success(
        api.create_price_submission(
            factories.price_submission_payload(
                vendor["id"], milk_item["id"], cycle["id"], 320
            ),
            vendor_headers,
        ),
        201,
    )

    # One millisecond before the due instant is still strictly before it.
    fixtures.set_clock(api, "2026-08-31T23:59:59.999Z")
    validate_success(
        api.create_price_submission(
            factories.price_submission_payload(
                vendor["id"], juice_item["id"], cycle["id"], 118
            ),
            vendor_headers,
        ),
        201,
    )

    # The due instant is excluded, and the cycle status is not what refuses it.
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    validate_error(
        api.create_price_submission(
            factories.price_submission_payload(
                vendor["id"], cereal_item["id"], cycle["id"], 250
            ),
            vendor_headers,
        ),
        ApiErrorId.SUBMISSION_WINDOW_CLOSED.value,
    )
    assert_field_values(
        fixtures.get_price_cycle(api, cycle["id"]),
        status=PriceCycleStatus.OPEN.value,
    )

    _, meta = validate_paginated(
        api.list_price_submissions(
            SUPERVISOR_HEADERS,
            {"vendor_id": vendor["id"], "price_cycle_id": cycle["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 2, (
        f"only the two in-window submissions may have been written: {meta}"
    )


def test_publish_ceilings_returns_inline_summary_counts(api):
    """
    Publishing answers inline with the cycle, the published and skipped pair counts, the
    number of rows it superseded, and the publication instant.

    "Publishing moves a cycle `CLOSED → PUBLISHED` — again `ERR_INVALID_CYCLE_STATE` for any other status — stamps `published_at`, and performs three passes."
    "First, every PriceCeiling of this cycle still in `PROVISIONAL` moves to `SUPERSEDED` with `superseded_reason` `PROVISIONAL_REPLACED`."
    "Second, the same pair sweep runs again and writes a fresh PriceCeiling row with `status` `ACTIVE` for every pair with a non-empty candidate set, setting `published_ceiling_count` and `skipped_pair_count` from that sweep."
    "The response to publication reports the `price_cycle_id`, the resulting `status`, the `published_ceiling_count`, the `skipped_pair_count`, a `superseded_ceiling_count` covering every row this call moved to `SUPERSEDED`, and the `published_at` instant."
    "For each pair with a non-empty candidate set, a PriceCeiling row is written with `status` `PROVISIONAL`; the number written becomes the cycle's `provisional_ceiling_count`, and the number of pairs skipped for having an empty candidate set becomes its `skipped_pair_count`."
    "If the peer list is empty, the pair is skipped entirely: no PriceCeiling row is written for it and the cycle's `skipped_pair_count` rises by one."
    "When the peer count falls short, `basis` is `STATEWIDE_FALLBACK` and the candidate set is rebuilt with the identical filter but **without** the peer-group restriction, restricted to submissions from vendors whose own peer group has `status` `ACTIVE`; that broader list is likewise sorted ascending by price with the `created_at` tie-break."

    Design: Corner/endpoints/publish_ceilings_returns_inline_summary_counts
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    bundle = fixtures.authorized_vendor_setup(api)
    supermarket_group_id = bundle["peer_group"]["id"]
    cycle_id = bundle["cycle"]["id"]

    # A second ACTIVE peer group nobody submitted into, so the sweep has a pair to skip.
    pharmacy_group = fixtures.create_peer_group(
        api,
        code="PG-PHARM-A",
        store_type=StoreType.PHARMACY.value,
        min_monthly_redemption_cents=0,
        max_monthly_redemption_cents=None,
        mar_method=MarMethod.PEER_MEDIAN.value,
        competitive_allowance_pct=0.10,
        min_submissions_for_ceiling=3,
        min_stock_multiplier=0.5,
    )

    closed = validate_success(api.close_price_cycle(cycle_id, None, SUPERVISOR_HEADERS))
    assert_field_values(
        closed,
        status=PriceCycleStatus.CLOSED.value,
        provisional_ceiling_count=1,  # only the supermarket pair had a candidate
        skipped_pair_count=1,  # the pharmacy pair had an empty peer list
    )

    summary = validate_success(
        api.publish_ceilings(cycle_id, None, SUPERVISOR_HEADERS)
    )
    assert_field_values(
        summary,
        price_cycle_id=cycle_id,
        status=PriceCycleStatus.PUBLISHED.value,
        published_ceiling_count=1,
        skipped_pair_count=1,
        superseded_ceiling_count=1,  # the one PROVISIONAL row this call retired
        published_at="2026-08-01T00:00:00.000Z",
    )

    superseded, superseded_meta = validate_paginated(
        api.list_price_ceilings(
            SUPERVISOR_HEADERS,
            {
                "price_cycle_id": cycle_id,
                "status": CeilingStatus.SUPERSEDED.value,
                "limit": 100,
            },
        )
    )
    assert superseded_meta["total_count"] == 1, (
        f"exactly one row should have been superseded: {superseded_meta}"
    )
    assert_field_values(
        superseded[0],
        superseded_reason=SupersededReason.PROVISIONAL_REPLACED.value,
        mar_cents=336,  # the provisional figure: 320 x 1.05, under the 400 cap
    )

    active, active_meta = validate_paginated(
        api.list_price_ceilings(
            SUPERVISOR_HEADERS,
            {
                "price_cycle_id": cycle_id,
                "status": CeilingStatus.ACTIVE.value,
                "limit": 100,
            },
        )
    )
    assert active_meta["total_count"] == 1, (
        f"exactly one ACTIVE row should have been published: {active_meta}"
    )
    assert_field_values(active[0], peer_group_id=supermarket_group_id)
    assert_ceiling_derivation(
        active[0],
        basis=CeilingBasis.STATEWIDE_FALLBACK.value,  # 1 peer falls short of 3
        peer_submission_count=1,
        contributing_submission_count=1,
        base_cents=320,
        cap_cents=400.0,  # 1.25 x 320
        cap_binding=False,  # 400 is not strictly below 336
        mar_cents=336,  # round_half_up(320 x 1.05)
    )

    _, pharmacy_meta = validate_paginated(
        api.list_price_ceilings(
            SUPERVISOR_HEADERS,
            {
                "price_cycle_id": cycle_id,
                "peer_group_id": pharmacy_group["id"],
                "limit": 100,
            },
        )
    )
    assert pharmacy_meta["total_count"] == 0, (
        f"a skipped pair must leave no ceiling row behind: {pharmacy_meta}"
    )


def test_authorize_response_reflects_all_derived_state_immediately(api):
    """
    The authorization response already carries every derived value, and the peer group's
    membership count and version are visible on the next read with no refresh step.

    "Authorizing a vendor is a supervisor decision that turns a reviewed application into an operating WIC vendor, advancing `authorization_status` from `IN_REVIEW` to `AUTHORIZED`."
    "On success the vendor gains `authorized_at` from the logical clock and a `reauthorization_due_at` set to thirty-six calendar months after `authorized_at`."
    "The assigned peer group's `member_count` rises by one and its `version` increments by one, because the vendor has just entered the membership set of §2.9."
    "From that instant the server derives `training_expires_at` by adding twelve calendar months to `training_completed_at` under the month arithmetic of §2.5."
    "A peer group's `member_count` is the number of vendors assigned to it whose `authorization_status` is `AUTHORIZED`, `REAUTH_PENDING`, or `SUSPENDED`."
    "Vendors in `APPLICANT`, `IN_REVIEW`, `DENIED`, or `DISQUALIFIED` are not counted, and vendors with no peer group assigned are not counted at all."
    "Every transition into or out of that membership set adjusts the count by one and increments the peer group's `version` by one."
    "If no such claim exists, `avg_monthly_redemption_cents` falls back to the vendor's self-reported `reported_monthly_redemption_cents`."
    "The same request also recomputes `price_submission_complete` against the current price cycle — it stays false while no required item has an accepted submission — and clears `authorization_blocked_reason` back to null, because entering review resets any block inherited from an earlier round."

    Design: Corner/consistency_model/authorize_response_reflects_all_derived_state_immediately
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    catalogue = fixtures.bootstrap_catalogue(api)
    peer_group_id = catalogue["peer_group"]["id"]
    created_version = catalogue["peer_group"]["version"]

    vendor = fixtures.vendor_in_review(api)  # training completed 2026-07-15
    submission = fixtures.submit_price(
        api, vendor["id"], catalogue["milk_item"]["id"], catalogue["cycle"]["id"], 320
    )
    fixtures.accept_submission(api, submission["id"])

    before = fixtures.get_peer_group(api, peer_group_id)
    assert_field_values(
        before,
        member_count=0,  # an IN_REVIEW vendor is not a member
        version=created_version,  # so assignment alone did not mutate the group
    )
    assert_field_values(
        fixtures.get_vendor(api, vendor["id"]),
        authorization_status=VendorStatus.IN_REVIEW.value,
        peer_group_id=peer_group_id,
    )

    authorized = validate_success(
        api.authorize_vendor(vendor["id"], None, SUPERVISOR_HEADERS)
    )
    assert_field_values(
        authorized,
        id=vendor["id"],
        authorization_status=VendorStatus.AUTHORIZED.value,
        authorized_at="2026-08-01T00:00:00.000Z",  # the logical clock
        # 36 calendar months after 2026-08-01, time of day preserved
        reauthorization_due_at="2029-08-01T00:00:00.000Z",
        # 12 calendar months after the 2026-07-15 training
        training_expires_at="2027-07-15T00:00:00.000Z",
        authorization_blocked_reason=None,
        avg_monthly_redemption_cents=6_000_000,  # no claim exists, so the reported figure
        peer_group_id=peer_group_id,
    )

    # The very next read agrees with the response, with no intervening write.
    assert_field_values(
        fixtures.get_vendor(api, vendor["id"]),
        authorization_status=VendorStatus.AUTHORIZED.value,
        authorized_at="2026-08-01T00:00:00.000Z",
        reauthorization_due_at="2029-08-01T00:00:00.000Z",
        training_expires_at="2027-07-15T00:00:00.000Z",
        authorization_blocked_reason=None,
        avg_monthly_redemption_cents=6_000_000,
    )

    after = fixtures.get_peer_group(api, peer_group_id)
    assert_field_values(
        after,
        member_count=1,  # the vendor entered the membership set in the same transaction
        version=created_version + 1,
    )

    members, meta = validate_paginated(
        api.list_vendors(
            SUPERVISOR_HEADERS,
            {
                "peer_group_id": peer_group_id,
                "authorization_status": VendorStatus.AUTHORIZED.value,
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 1, (
        f"the authorized vendor should be immediately listable: {meta}"
    )
    assert_field_values(members[0], id=vendor["id"])
