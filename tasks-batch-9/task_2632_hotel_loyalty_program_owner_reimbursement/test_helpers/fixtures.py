"""Composite fixture builders.

Every test starts against an empty database, so all preconditions have to be built
through the programme's own endpoints. Each builder here drives a real request
sequence and returns the resulting rows.

Builders use ``get_success_data`` internally: a fixture is scaffolding, not the
assertion under test. Ownership-gated calls are threaded with per-instance headers
(``make_hotel_owner_headers(hotel_id)`` / ``make_member_headers(member_id)``)
rather than a shared identity.
"""

from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .constants import CLOCK_DEFAULT_UTC
from .test_users import (
    make_admin_headers,
    make_care_agent_headers,
    make_hotel_owner_headers,
    make_member_headers,
)


# ----------------------------------------------------------------------
# Tier 0 - dates and the logical clock
# ----------------------------------------------------------------------
def iso_instant(day: str, time_part: str = "00:00:00") -> str:
    """A calendar day and a wall time as one logical-clock instant."""
    return f"{day}T{time_part}Z"


def add_days(day: str, days: int) -> str:
    """Calendar arithmetic on a YYYY-MM-DD string."""
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def days_between(earlier: str, later: str) -> int:
    return (date.fromisoformat(later) - date.fromisoformat(earlier)).days


def set_clock(client, current_utc: str, headers=None) -> dict:
    """Move the logical programme clock."""
    return get_success_data(
        client.set_clock(current_utc, headers or make_admin_headers())
    )


def set_clock_to_day(client, day: str, headers=None) -> dict:
    return set_clock(client, iso_instant(day), headers)


def reset_clock(client) -> dict:
    """Return the clock to the instant it reads at server start."""
    return set_clock(client, CLOCK_DEFAULT_UTC)


# ----------------------------------------------------------------------
# Tier 1 - properties, rate plans, award prices, blackout calendar
# ----------------------------------------------------------------------
def create_onboarding_hotel(client, **overrides) -> dict:
    """A property in ONBOARDING with no rate plan yet."""
    return get_success_data(
        client.create_hotel(f.create_hotel_payload(**overrides), make_admin_headers())
    )


def add_rate_plan(
    client, hotel_id: str, rate_code: str = "BAR", rate_category: str = "TRANSIENT"
) -> dict:
    return get_success_data(
        client.create_rate_plan(
            hotel_id,
            f.create_rate_plan_payload(rate_code=rate_code, rate_category=rate_category),
            make_admin_headers(),
        )
    )


def activate_hotel(client, hotel_id: str) -> dict:
    return get_success_data(client.activate_hotel(hotel_id, make_admin_headers()))


def read_hotel(client, hotel_id: str) -> dict:
    return get_success_data(client.get_hotel(hotel_id, make_admin_headers()))


def hotel_version(client, hotel_id: str) -> int:
    """The property's current version, for an optimistic-concurrency field."""
    return read_hotel(client, hotel_id)["version"]


def create_active_hotel(
    client, *, rate_code: str = "BAR", rate_category: str = "TRANSIENT", **overrides
) -> dict:
    """A property carried all the way to ACTIVE, with one rate plan.

    Returns a bundle: ``hotel`` (as it reads after activation), ``rate_plan`` and
    ``owner_headers`` for the property's own owner.
    """
    hotel = create_onboarding_hotel(client, **overrides)
    rate_plan = add_rate_plan(
        client, hotel["id"], rate_code=rate_code, rate_category=rate_category
    )
    activated = activate_hotel(client, hotel["id"])
    return {
        "hotel": activated,
        "rate_plan": rate_plan,
        "owner_headers": make_hotel_owner_headers(hotel["id"]),
    }


def refresh_performance(
    client, hotel_id: str, occupancy_pct: float, adr_cents: int
) -> dict:
    return get_success_data(
        client.refresh_hotel_performance(
            hotel_id,
            f.performance_refresh_payload(
                trailing_12m_occupancy_pct=occupancy_pct,
                trailing_12m_adr_cents=adr_cents,
            ),
            make_admin_headers(),
        )
    )


def terminate_hotel(client, hotel_id: str, reason: str = "Franchise exit") -> dict:
    return get_success_data(
        client.terminate_hotel(
            hotel_id,
            f.terminate_hotel_payload(termination_reason=reason),
            make_admin_headers(),
        )
    )


def publish_pricing(
    client,
    hotel_id: str,
    *,
    season: str = "STANDARD",
    window_start_date: str = "2026-01-01",
    window_end_date: str = "2026-12-31",
    points_per_night: int = 40_000,
    cash_copay_cents: int = 0,
    min_tier_required: str = "BASE",
    award_allotment_per_night: int = 5,
) -> dict:
    """Publish one award price window at the property."""
    return get_success_data(
        client.create_redemption_pricing(
            hotel_id,
            f.create_redemption_pricing_payload(
                season=season,
                window_start_date=window_start_date,
                window_end_date=window_end_date,
                points_per_night=points_per_night,
                cash_copay_cents=cash_copay_cents,
                min_tier_required=min_tier_required,
                award_allotment_per_night=award_allotment_per_night,
            ),
            make_admin_headers(),
        )
    )


def publish_standard_pricing(client, hotel_id: str, **overrides) -> dict:
    return publish_pricing(client, hotel_id, season="STANDARD", **overrides)


def publish_peak_pricing(
    client,
    hotel_id: str,
    *,
    window_start_date: str = "2026-12-20",
    window_end_date: str = "2026-12-31",
    points_per_night: int = 60_000,
    **overrides,
) -> dict:
    return publish_pricing(
        client,
        hotel_id,
        season="PEAK",
        window_start_date=window_start_date,
        window_end_date=window_end_date,
        points_per_night=points_per_night,
        **overrides,
    )


def draft_blackout(
    client,
    hotel_id: str,
    start_date: str,
    end_date: str,
    scope: str = "ALL_REDEMPTIONS",
    headers=None,
) -> dict:
    return get_success_data(
        client.create_blackout_window(
            hotel_id,
            f.create_blackout_window_payload(
                start_date=start_date, end_date=end_date, scope=scope
            ),
            headers or make_admin_headers(),
        )
    )


def activate_blackout(client, window_id: str) -> dict:
    return get_success_data(
        client.activate_blackout_window(window_id, make_admin_headers())
    )


def create_active_blackout(
    client, hotel_id: str, start_date: str, end_date: str, scope: str = "ALL_REDEMPTIONS"
) -> dict:
    """A blackout window drafted and then activated, so it really does block."""
    window = draft_blackout(client, hotel_id, start_date, end_date, scope)
    return activate_blackout(client, window["id"])


def revoke_blackout(client, window_id: str, reason: str = "Forecast revised") -> dict:
    return get_success_data(
        client.revoke_blackout_window(
            window_id,
            f.revoke_blackout_window_payload(revoke_reason=reason),
            make_admin_headers(),
        )
    )


# ----------------------------------------------------------------------
# Tier 2 - members, partners, point sales and goodwill
# ----------------------------------------------------------------------
def enroll_member(client, **overrides) -> dict:
    """A member at BASE with every counter at zero."""
    return get_success_data(
        client.create_member(f.create_member_payload(**overrides), make_admin_headers())
    )


def read_member(client, member_id: str) -> dict:
    return get_success_data(client.get_member(member_id, make_admin_headers()))


def member_version(client, member_id: str) -> int:
    return read_member(client, member_id)["version"]


def grant_goodwill_points(client, member_id: str, points: int, reason: str = None) -> dict:
    """Move a member's balance directly. The response body is a ledger entry, so
    the refreshed member is read back separately."""
    payload = f.point_adjustment_payload(
        member_id, points, member_version(client, member_id)
    )
    if reason is not None:
        payload["adjustment_reason"] = reason
    return get_success_data(client.create_point_adjustment(payload, make_admin_headers()))


def member_with_goodwill_points(client, points: int, **overrides) -> dict:
    """A member holding a balance that came in as an explicit grant."""
    member = enroll_member(client, **overrides)
    grant_goodwill_points(client, member["id"], points)
    return read_member(client, member["id"])


def create_partner(client, **overrides) -> dict:
    return get_success_data(
        client.create_partner(f.create_partner_payload(**overrides), make_admin_headers())
    )


def record_purchase(
    client,
    member_id: str,
    points_quantity: int,
    channel: str = "DIRECT_PURCHASE",
    partner_id: str = None,
    headers=None,
) -> dict:
    payload = f.create_point_purchase_payload(
        member_id, points_quantity=points_quantity, channel=channel
    )
    if partner_id is not None:
        payload["partner_id"] = partner_id
    return get_success_data(
        client.create_point_purchase(payload, headers or make_admin_headers())
    )


def settle_purchase(client, purchase_id: str) -> dict:
    return get_success_data(
        client.settle_point_purchase(purchase_id, make_admin_headers())
    )


def refund_purchase(client, purchase_id: str, reason: str = "Unauthorized order") -> dict:
    return get_success_data(
        client.refund_point_purchase(
            purchase_id,
            f.refund_point_purchase_payload(refund_reason=reason),
            make_admin_headers(),
        )
    )


def settled_purchase(
    client,
    member_id: str,
    points_quantity: int,
    channel: str = "DIRECT_PURCHASE",
    partner_id: str = None,
) -> dict:
    """A purchase carried to SETTLED, so its cash is in the fund and its points
    are in the member's balance."""
    purchase = record_purchase(
        client, member_id, points_quantity, channel=channel, partner_id=partner_id
    )
    return settle_purchase(client, purchase["id"])


def member_funded_by_purchase(
    client,
    points_quantity: int,
    channel: str = "DIRECT_PURCHASE",
    partner_id: str = None,
    **overrides,
) -> dict:
    """A member whose balance arrived through a settled point sale, which also
    puts programme cash in the fund.

    Returns a bundle: ``member`` as it reads after settlement, ``purchase`` and
    ``member_headers``.
    """
    member = enroll_member(client, **overrides)
    purchase = settled_purchase(
        client, member["id"], points_quantity, channel=channel, partner_id=partner_id
    )
    return {
        "member": read_member(client, member["id"]),
        "purchase": purchase,
        "member_headers": make_member_headers(member["id"]),
    }


# ----------------------------------------------------------------------
# Tier 3 - paid stays, earnings and elite benefit obligations
# ----------------------------------------------------------------------
def capture_stay(
    client,
    hotel_id: str,
    member_id: str,
    rate_plan_id: str,
    checkin_date: str,
    checkout_date: str,
    room_revenue_cents: int,
    incidental_revenue_cents: int = None,
    headers=None,
) -> dict:
    """A completed paid stay captured in PENDING_POSTING."""
    payload = f.create_stay_payload(
        member_id,
        hotel_id,
        rate_plan_id,
        checkin_date=checkin_date,
        checkout_date=checkout_date,
        room_revenue_cents=room_revenue_cents,
    )
    if incidental_revenue_cents is not None:
        payload["incidental_revenue_cents"] = incidental_revenue_cents
    return get_success_data(client.create_stay(payload, headers or make_admin_headers()))


def post_stay(client, stay_id: str, headers=None) -> dict:
    return get_success_data(client.post_stay(stay_id, headers or make_admin_headers()))


def read_stay(client, stay_id: str) -> dict:
    return get_success_data(client.get_stay(stay_id, make_admin_headers()))


def posted_stay(
    client,
    hotel_id: str,
    member_id: str,
    rate_plan_id: str,
    checkin_date: str,
    checkout_date: str,
    room_revenue_cents: int,
    incidental_revenue_cents: int = None,
) -> dict:
    """A stay captured and then posted, so its points, fee, tier re-derivation and
    benefit obligations have all happened."""
    stay = capture_stay(
        client,
        hotel_id,
        member_id,
        rate_plan_id,
        checkin_date,
        checkout_date,
        room_revenue_cents,
        incidental_revenue_cents,
    )
    return post_stay(client, stay["id"])


def dispute_stay(client, stay_id: str, reason: str = "Rate challenged", headers=None) -> dict:
    return get_success_data(
        client.dispute_stay(
            stay_id,
            f.dispute_stay_payload(dispute_reason=reason),
            headers or make_admin_headers(),
        )
    )


def adjust_stay(client, stay_id: str, room_revenue_cents: int = None) -> dict:
    payload = {}
    if room_revenue_cents is not None:
        payload["room_revenue_cents"] = room_revenue_cents
    return get_success_data(client.adjust_stay(stay_id, payload, make_admin_headers()))


def void_stay(client, stay_id: str, reason: str = "Duplicate folio") -> dict:
    return get_success_data(
        client.void_stay(
            stay_id, f.void_stay_payload(void_reason=reason), make_admin_headers()
        )
    )


def obligations_for_stay(client, stay_id: str) -> list:
    """Every elite benefit obligation the posting of one stay synthesised."""
    response = client.list_benefit_deliveries(
        make_admin_headers(), params={"stay_id": stay_id, "limit": 100, "offset": 0}
    )
    rows, _meta = validate_paginated(response)
    return rows


def obligation_of_type(client, stay_id: str, benefit_type: str) -> dict:
    for row in obligations_for_stay(client, stay_id):
        if row["benefit_type"] == benefit_type:
            return row
    raise AssertionError(f"stay {stay_id} carries no {benefit_type} obligation")


def deliver_obligation(client, delivery_id: str, headers=None) -> dict:
    return get_success_data(
        client.deliver_benefit(delivery_id, headers or make_admin_headers())
    )


def deny_obligation(
    client, delivery_id: str, reason: str = "No inventory available", headers=None
) -> dict:
    return get_success_data(
        client.deny_benefit(
            delivery_id,
            f.deny_benefit_payload(denial_reason=reason),
            headers or make_admin_headers(),
        )
    )


def denied_obligation(client, stay_id: str, benefit_type: str = "UPGRADE") -> dict:
    """One obligation of a posted stay carried into a refused reading."""
    obligation = obligation_of_type(client, stay_id, benefit_type)
    return deny_obligation(client, obligation["id"])


def drive_member_to_nights(
    client,
    hotel_id: str,
    member_id: str,
    rate_plan_id: str,
    nights: int,
    *,
    checkin_date: str = "2026-05-01",
    room_revenue_cents: int = None,
) -> dict:
    """Post one stay long enough to move the member's night count to ``nights``.

    Elite standing is re-derived from the qualifying night count, so a single
    multi-night stay on an elite-counting rate plan is the cheapest way to reach a
    given tier.
    """
    revenue = room_revenue_cents if room_revenue_cents is not None else nights * 10_000
    return posted_stay(
        client,
        hotel_id,
        member_id,
        rate_plan_id,
        checkin_date,
        add_days(checkin_date, nights),
        revenue,
    )


def stays_of_hotel(client, hotel_id: str) -> list:
    response = client.list_stays(
        make_admin_headers(), params={"hotel_id": hotel_id, "limit": 100, "offset": 0}
    )
    rows, _meta = validate_paginated(response)
    return rows


def ledger_of_member(client, member_id: str, **filters) -> list:
    """Every ledger row of one member, drained through the pagination envelope."""
    params = {"member_id": member_id, "limit": 100, "offset": 0}
    params.update(filters)
    response = client.list_ledger_entries(make_admin_headers(), params=params)
    rows, _meta = validate_paginated(response)
    return rows


def ledger_for_stay(client, stay_id: str) -> list:
    response = client.list_ledger_entries(
        make_admin_headers(), params={"source_stay_id": stay_id, "limit": 100, "offset": 0}
    )
    rows, _meta = validate_paginated(response)
    return rows


def ledger_for_redemption(client, redemption_id: str) -> list:
    response = client.list_ledger_entries(
        make_admin_headers(),
        params={"source_redemption_id": redemption_id, "limit": 100, "offset": 0},
    )
    rows, _meta = validate_paginated(response)
    return rows


def ledger_for_purchase(client, purchase_id: str) -> list:
    response = client.list_ledger_entries(
        make_admin_headers(),
        params={"source_purchase_id": purchase_id, "limit": 100, "offset": 0},
    )
    rows, _meta = validate_paginated(response)
    return rows


# ----------------------------------------------------------------------
# Tier 4 - award bookings and the reimbursement chain
# ----------------------------------------------------------------------
def book_award(
    client,
    member_id: str,
    hotel_id: str,
    checkin_date: str,
    checkout_date: str,
    headers=None,
    expected_hotel_version: int = None,
) -> dict:
    """Book an award stay, reading the property's current version unless the
    caller wants to pin a stale one deliberately."""
    version = (
        expected_hotel_version
        if expected_hotel_version is not None
        else hotel_version(client, hotel_id)
    )
    payload = f.create_redemption_payload(
        member_id,
        hotel_id,
        version,
        checkin_date=checkin_date,
        checkout_date=checkout_date,
    )
    return get_success_data(
        client.create_redemption(payload, headers or make_admin_headers())
    )


def confirm_award(client, redemption_id: str, headers=None) -> dict:
    return get_success_data(
        client.confirm_redemption(redemption_id, headers or make_admin_headers())
    )


def complete_award_stay(client, redemption_id: str, headers=None) -> dict:
    return get_success_data(
        client.complete_redemption_stay(redemption_id, headers or make_admin_headers())
    )


def no_show_award(client, redemption_id: str, headers=None) -> dict:
    return get_success_data(
        client.no_show_redemption(redemption_id, headers or make_admin_headers())
    )


def cancel_award(
    client, redemption_id: str, reason: str = "Trip cancelled", headers=None
) -> dict:
    return get_success_data(
        client.cancel_redemption(
            redemption_id,
            f.cancel_redemption_payload(cancel_reason=reason),
            headers or make_admin_headers(),
        )
    )


def read_redemption(client, redemption_id: str) -> dict:
    return get_success_data(client.get_redemption(redemption_id, make_admin_headers()))


def accrued_award(
    client,
    member_id: str,
    hotel_id: str,
    checkin_date: str,
    checkout_date: str,
    completion_day: str = None,
) -> dict:
    """An award booking driven all the way to STAYED, so its reimbursement has
    accrued under the accrual reading.

    The clock is advanced to ``completion_day`` (the day after checkout by
    default) because completion requires the checkout date to have elapsed.
    """
    redemption = book_award(client, member_id, hotel_id, checkin_date, checkout_date)
    confirm_award(client, redemption["id"])
    set_clock_to_day(client, completion_day or add_days(checkout_date, 1))
    return complete_award_stay(client, redemption["id"])


def open_batch(client, hotel_id: str, period_month: str, headers=None) -> dict:
    return get_success_data(
        client.create_reimbursement_batch(
            f.create_reimbursement_batch_payload(hotel_id, period_month),
            headers or make_admin_headers(),
        )
    )


def release_batch(client, batch_id: str, releaser_id: str = "op-release-1") -> dict:
    return get_success_data(
        client.release_batch(batch_id, make_admin_headers(releaser_id))
    )


def approve_batch(client, batch_id: str, approver_id: str = "op-approve-1") -> dict:
    return get_success_data(
        client.approve_batch(batch_id, make_admin_headers(approver_id))
    )


def reject_batch(
    client, batch_id: str, reason: str = "Attestation missing", rejecter_id: str = "op-approve-1"
) -> dict:
    return get_success_data(
        client.reject_batch(
            batch_id,
            f.reject_batch_payload(rejection_reason=reason),
            make_admin_headers(rejecter_id),
        )
    )


def pay_batch(client, batch_id: str, payer_id: str = "op-pay-1") -> dict:
    return get_success_data(client.pay_batch(batch_id, make_admin_headers(payer_id)))


def read_batch(client, batch_id: str) -> dict:
    return get_success_data(
        client.get_reimbursement_batch(batch_id, make_admin_headers())
    )


def released_batch(client, hotel_id: str, period_month: str, releaser_id: str = "op-release-1") -> dict:
    batch = open_batch(client, hotel_id, period_month)
    return release_batch(client, batch["id"], releaser_id)


def approved_batch(
    client,
    hotel_id: str,
    period_month: str,
    releaser_id: str = "op-release-1",
    approver_id: str = "op-approve-1",
) -> dict:
    batch = released_batch(client, hotel_id, period_month, releaser_id)
    return approve_batch(client, batch["id"], approver_id)


def paid_batch(
    client,
    hotel_id: str,
    period_month: str,
    releaser_id: str = "op-release-1",
    approver_id: str = "op-approve-1",
    payer_id: str = "op-pay-1",
) -> dict:
    """A batch carried from OPEN to PAID by three distinct operators, which is the
    minimum the duty rules allow."""
    batch = approved_batch(client, hotel_id, period_month, releaser_id, approver_id)
    return pay_batch(client, batch["id"], payer_id)


# ----------------------------------------------------------------------
# Tier 4b - programme fund
# ----------------------------------------------------------------------
def read_fund(client) -> dict:
    return get_success_data(client.get_program_fund(make_admin_headers()))


def revalue_fund(client) -> dict:
    return get_success_data(client.revalue_program_fund(make_admin_headers()))


def set_breakage_rate(client, breakage_rate_pct: float) -> dict:
    return get_success_data(
        client.set_breakage_rate(
            f.breakage_rate_payload(breakage_rate_pct=breakage_rate_pct),
            make_admin_headers(),
        )
    )


# ----------------------------------------------------------------------
# Tier 4c - member complaints
# ----------------------------------------------------------------------
def file_complaint(
    client,
    member_id: str,
    subject_type: str = "POINT_SHORTFALL",
    related_delivery_id: str = None,
    headers=None,
) -> dict:
    payload = f.create_complaint_payload(member_id, subject_type=subject_type)
    if related_delivery_id is not None:
        payload["related_delivery_id"] = related_delivery_id
    return get_success_data(
        client.create_complaint(payload, headers or make_care_agent_headers())
    )


def review_complaint(client, complaint_id: str, headers=None) -> dict:
    return get_success_data(
        client.review_complaint(complaint_id, headers or make_care_agent_headers())
    )


def request_complaint_info(client, complaint_id: str, headers=None) -> dict:
    return get_success_data(
        client.request_complaint_info(complaint_id, headers or make_care_agent_headers())
    )


def provide_complaint_info(client, complaint_id: str, headers=None) -> dict:
    return get_success_data(
        client.provide_complaint_info(
            complaint_id,
            f.provide_complaint_info_payload(),
            headers or make_care_agent_headers(),
        )
    )


def resolve_complaint(
    client,
    complaint_id: str,
    resolution: str = "Reviewed and closed.",
    goodwill_points: int = None,
    headers=None,
) -> dict:
    payload = f.resolve_complaint_payload(resolution=resolution)
    if goodwill_points is not None:
        payload["goodwill_points"] = goodwill_points
    return get_success_data(
        client.resolve_complaint(
            complaint_id, payload, headers or make_care_agent_headers()
        )
    )


def escalate_complaint(client, complaint_id: str, headers=None) -> dict:
    return get_success_data(
        client.escalate_complaint(complaint_id, headers or make_care_agent_headers())
    )


def adjudicate_complaint(
    client, complaint_id: str, adjudication_outcome: str = "DELIVERY_ORDERED"
) -> dict:
    return get_success_data(
        client.adjudicate_complaint(
            complaint_id,
            f.adjudicate_complaint_payload(adjudication_outcome=adjudication_outcome),
            make_admin_headers(),
        )
    )


def read_complaint(client, complaint_id: str) -> dict:
    return get_success_data(client.get_complaint(complaint_id, make_admin_headers()))


def complaint_under_review(
    client, member_id: str, subject_type: str = "POINT_SHORTFALL", related_delivery_id: str = None
) -> dict:
    complaint = file_complaint(
        client, member_id, subject_type=subject_type, related_delivery_id=related_delivery_id
    )
    return review_complaint(client, complaint["id"])


def complaint_resolved_upheld(
    client, member_id: str, subject_type: str = "POINT_SHORTFALL", related_delivery_id: str = None
) -> dict:
    """A complaint carried to the one status escalation is reachable from."""
    complaint = complaint_under_review(
        client, member_id, subject_type=subject_type, related_delivery_id=related_delivery_id
    )
    return resolve_complaint(client, complaint["id"])


def complaint_escalated(
    client, member_id: str, subject_type: str = "POINT_SHORTFALL", related_delivery_id: str = None
) -> dict:
    complaint = complaint_resolved_upheld(
        client, member_id, subject_type=subject_type, related_delivery_id=related_delivery_id
    )
    return escalate_complaint(client, complaint["id"])


# ----------------------------------------------------------------------
# Tier 5 - full-lifecycle shortcuts
# ----------------------------------------------------------------------
def award_ready_program(
    client,
    *,
    member_points: int = 100_000,
    points_per_night: int = 40_000,
    award_allotment_per_night: int = 5,
    min_tier_required: str = "BASE",
    cash_copay_cents: int = 0,
    **hotel_overrides,
) -> dict:
    """Everything an award booking needs: an ACTIVE property with a rate plan, a
    published standard price window, and a member funded by a settled point sale
    so the fund holds cash as well.

    Returns a bundle with ``hotel``, ``rate_plan``, ``owner_headers``, ``pricing``,
    ``member``, ``member_headers`` and ``purchase``.
    """
    property_bundle = create_active_hotel(client, **hotel_overrides)
    pricing = publish_standard_pricing(
        client,
        property_bundle["hotel"]["id"],
        points_per_night=points_per_night,
        award_allotment_per_night=award_allotment_per_night,
        min_tier_required=min_tier_required,
        cash_copay_cents=cash_copay_cents,
    )
    member_bundle = member_funded_by_purchase(client, member_points)
    bundle = dict(property_bundle)
    bundle["pricing"] = pricing
    bundle.update(member_bundle)
    return bundle


def accrued_award_program(
    client,
    *,
    checkin_date: str = "2026-09-08",
    checkout_date: str = "2026-09-10",
    completion_day: str = None,
    **kwargs,
) -> dict:
    """An award booking already STAYED and ACCRUED, ready for a batch to pick up."""
    bundle = award_ready_program(client, **kwargs)
    bundle["redemption"] = accrued_award(
        client,
        bundle["member"]["id"],
        bundle["hotel"]["id"],
        checkin_date,
        checkout_date,
        completion_day,
    )
    return bundle


def hotel_in_fee_delinquency(
    client,
    *,
    room_revenue_cents: int = 6_000_000,
    nights: int = 10,
    checkin_date: str = "2026-06-01",
    program_fee_pct: float = 0.05,
    **hotel_overrides,
) -> dict:
    """A property pushed past the fee threshold by one large group posting.

    Group business is fee-assessed but never accrues elite nights, which keeps the
    member's standing out of the picture.
    """
    hotel_overrides.setdefault("program_fee_pct", program_fee_pct)
    property_bundle = create_active_hotel(
        client, rate_code="GRP", rate_category="GROUP", **hotel_overrides
    )
    member = enroll_member(client)
    stay = posted_stay(
        client,
        property_bundle["hotel"]["id"],
        member["id"],
        property_bundle["rate_plan"]["id"],
        checkin_date,
        add_days(checkin_date, nights),
        room_revenue_cents,
    )
    bundle = dict(property_bundle)
    bundle["hotel"] = read_hotel(client, property_bundle["hotel"]["id"])
    bundle["member"] = read_member(client, member["id"])
    bundle["member_headers"] = make_member_headers(member["id"])
    bundle["stay"] = stay
    return bundle


def member_at_tier(
    client, tier: str, *, checkin_date: str = "2026-05-01", **hotel_overrides
) -> dict:
    """A member standing at the requested elite tier, reached by night count.

    Returns a bundle with ``hotel``, ``rate_plan``, ``owner_headers``, ``member``,
    ``member_headers`` and the qualifying ``stay``.
    """
    nights_for_tier = {"BASE": 0, "SILVER": 10, "GOLD": 30, "PLATINUM": 50}
    nights = nights_for_tier[tier]
    property_bundle = create_active_hotel(client, **hotel_overrides)
    member = enroll_member(client)
    stay = None
    if nights:
        stay = drive_member_to_nights(
            client,
            property_bundle["hotel"]["id"],
            member["id"],
            property_bundle["rate_plan"]["id"],
            nights,
            checkin_date=checkin_date,
        )
    bundle = dict(property_bundle)
    bundle["hotel"] = read_hotel(client, property_bundle["hotel"]["id"])
    bundle["member"] = read_member(client, member["id"])
    bundle["member_headers"] = make_member_headers(member["id"])
    bundle["stay"] = stay
    return bundle


def denied_benefit_program(
    client,
    *,
    tier: str = "SILVER",
    benefit_type: str = "UPGRADE",
    second_checkin_date: str = "2026-07-10",
    second_nights: int = 2,
    second_revenue_cents: int = 40_000,
    **hotel_overrides,
) -> dict:
    """A member standing at an elite tier with a later stay whose obligation the
    property refused, which is the precondition for a benefit-denial complaint.

    Returns the ``member_at_tier`` bundle plus ``benefit_stay`` and ``obligation``.
    """
    bundle = member_at_tier(client, tier, **hotel_overrides)
    benefit_stay = posted_stay(
        client,
        bundle["hotel"]["id"],
        bundle["member"]["id"],
        bundle["rate_plan"]["id"],
        second_checkin_date,
        add_days(second_checkin_date, second_nights),
        second_revenue_cents,
    )
    obligation = denied_obligation(client, benefit_stay["id"], benefit_type)
    bundle["benefit_stay"] = benefit_stay
    bundle["obligation"] = obligation
    bundle["hotel"] = read_hotel(client, bundle["hotel"]["id"])
    bundle["member"] = read_member(client, bundle["member"]["id"])
    return bundle
