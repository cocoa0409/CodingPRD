"""Composite setup helpers for the talent-agency booking domain.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before each test.

Identity threading: CastingDirector and Talent are entity-backed roles (PRD §2.1).
After a fixture creates such an entity, every ownership-gated call uses
make_casting_director_headers(cd_id) / make_talent_headers(talent_id) with the
real id — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_agent_headers,
    make_casting_director_headers,
    make_talent_headers,
)
from . import factories as f

AGENT = TEST_USERS["agent_headers"]


# ─── Low-level entity builders ────────────────────────
def create_agency(commission_rate_bps=1000, name="Stellar Talent"):
    resp = api_client.create_agency(
        f.create_agency_payload(name=name, commission_rate_bps=commission_rate_bps), AGENT
    )
    return get_success_data(resp)


def create_casting_director(display_name="Dana Cast", studio="BigPic"):
    resp = api_client.create_casting_director(
        f.create_casting_director_payload(display_name=display_name, studio=studio), AGENT
    )
    return get_success_data(resp)


def create_talent(agency_id, union_status="SAG", full_name="Tess Lead",
                  scale_rate_cents=100000):
    resp = api_client.create_talent(
        f.create_talent_payload(
            agency_id, full_name=full_name, union_status=union_status,
            scale_rate_cents=scale_rate_cents,
        ),
        AGENT,
    )
    return get_success_data(resp)


def create_comp_card(talent_id, **overrides):
    resp = api_client.create_comp_card(
        f.create_comp_card_payload(talent_id, **overrides), AGENT
    )
    return get_success_data(resp)


def roster_talent(talent_id):
    resp = api_client.roster_talent(talent_id, AGENT)
    return get_success_data(resp)


def create_casting_call(cd_id, media_type="STREAMING", usage_term_months=12,
                        shoot_start_date="2026-03-15T00:00:00Z",
                        shoot_end_date="2026-03-19T00:00:00Z",
                        offered_day_rate_cents=200000, title="Lead Spot"):
    cd_headers = make_casting_director_headers(cd_id)
    resp = api_client.create_casting_call(
        f.create_casting_call_payload(
            cd_id, title=title, media_type=media_type,
            usage_term_months=usage_term_months,
            shoot_start_date=shoot_start_date, shoot_end_date=shoot_end_date,
            offered_day_rate_cents=offered_day_rate_cents,
        ),
        cd_headers,
    )
    return get_success_data(resp)


def create_submission(call_id, talent_id, cc_id):
    resp = api_client.create_submission(
        f.create_submission_payload(call_id, talent_id, cc_id), AGENT
    )
    return get_success_data(resp)


def create_availability_hold(talent_id, start_date="2026-03-15T00:00:00Z",
                             end_date="2026-03-19T00:00:00Z",
                             hold_kind="CONFIRMED_BOOKING"):
    resp = api_client.create_availability_hold(
        f.create_availability_hold_payload(
            talent_id, start_date=start_date, end_date=end_date, hold_kind=hold_kind
        ),
        AGENT,
    )
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, AGENT)
    return get_success_data(resp)


def talent_version(talent_id):
    return get_success_data(api_client.get_talent(talent_id, AGENT))["version"]


# ─── Tier 2/3: Roster + casting building blocks ───────
def setup_rostered_talent(union_status="SAG", commission_rate_bps=1000,
                          scale_rate_cents=100000, full_name="Tess Lead"):
    """Agency + ROSTERED talent (one comp card) + casting director.

    Returns dict with agency, cd, talent, comp_card.
    """
    agency = create_agency(commission_rate_bps=commission_rate_bps)
    cd = create_casting_director()
    talent = create_talent(
        agency["id"], union_status=union_status, full_name=full_name,
        scale_rate_cents=scale_rate_cents,
    )
    comp_card = create_comp_card(talent["id"])
    roster_talent(talent["id"])
    return {"agency": agency, "cd": cd, "talent": talent, "comp_card": comp_card}


def setup_accepted_deal(union_status="SAG", commission_rate_bps=1000,
                        media_type="STREAMING", usage_term_months=12,
                        offer_day_rate_cents=200000,
                        shoot_start_date="2026-03-15T00:00:00Z",
                        shoot_end_date="2026-03-19T00:00:00Z"):
    """Roster a talent, open a casting call, submit, open a deal memo, offer and
    accept it. Returns dict with agency, cd, talent, comp_card, call, submission,
    deal_memo (in ACCEPTED).
    """
    base = setup_rostered_talent(
        union_status=union_status, commission_rate_bps=commission_rate_bps
    )
    cd_id, talent_id, cc_id = base["cd"]["id"], base["talent"]["id"], base["comp_card"]["id"]
    cd_headers = make_casting_director_headers(cd_id)
    talent_headers = make_talent_headers(talent_id)

    call = create_casting_call(
        cd_id, media_type=media_type, usage_term_months=usage_term_months,
        shoot_start_date=shoot_start_date, shoot_end_date=shoot_end_date,
        offered_day_rate_cents=offer_day_rate_cents,
    )
    submission = create_submission(call["id"], talent_id, cc_id)
    # Advance the submission to AUDITION_SCHEDULED so opening the deal memo can move
    # it to OFFER_EXTENDED (PRD §3.5: opening a memo advances a submission in
    # AUDITION_SCHEDULED/CALLBACK_SCHEDULED to OFFER_EXTENDED).
    schedule_audition_slot(cd_id, submission["id"])
    dm = get_success_data(
        api_client.create_deal_memo(
            f.create_deal_memo_payload(call["id"], talent_id, submission["id"]),
            cd_headers,
        )
    )
    get_success_data(
        api_client.offer_deal_memo(
            dm["id"],
            f.offer_payload(offer_day_rate_cents=offer_day_rate_cents,
                            offer_usage_term_months=usage_term_months),
            cd_headers,
        )
    )
    deal_memo = get_success_data(api_client.accept_deal_memo(dm["id"], talent_headers))
    base.update({"call": call, "submission": submission, "deal_memo": deal_memo})
    return base


def setup_pending_booking(union_status="SAG", commission_rate_bps=1000,
                          media_type="STREAMING", usage_term_months=12,
                          offer_day_rate_cents=200000,
                          shoot_start_date="2026-03-15T00:00:00Z",
                          shoot_end_date="2026-03-19T00:00:00Z",
                          hold_start="2026-03-15T00:00:00Z",
                          hold_end="2026-03-19T00:00:00Z",
                          booking_start="2026-03-15T00:00:00Z",
                          booking_end="2026-03-19T00:00:00Z"):
    """Accepted deal + CONFIRMED_BOOKING hold + a PENDING booking.

    Returns dict additionally carrying hold and booking. The booking's
    expected_talent_version is read fresh right before the create.
    """
    base = setup_accepted_deal(
        union_status=union_status, commission_rate_bps=commission_rate_bps,
        media_type=media_type, usage_term_months=usage_term_months,
        offer_day_rate_cents=offer_day_rate_cents,
        shoot_start_date=shoot_start_date, shoot_end_date=shoot_end_date,
    )
    talent_id = base["talent"]["id"]
    hold = create_availability_hold(
        talent_id, start_date=hold_start, end_date=hold_end,
        hold_kind="CONFIRMED_BOOKING",
    )
    tv = talent_version(talent_id)
    booking = get_success_data(
        api_client.create_booking(
            f.create_booking_payload(
                base["deal_memo"]["id"], talent_id, base["call"]["id"], hold["id"], tv,
                start_date=booking_start, end_date=booking_end,
            ),
            AGENT,
        )
    )
    base.update({"hold": hold, "booking": booking})
    return base


def setup_confirmed_booking(**kwargs):
    """PENDING booking advanced through confirm. Returns the setup_pending_booking
    dict with booking re-read in CONFIRMED state."""
    base = setup_pending_booking(**kwargs)
    talent_id = base["talent"]["id"]
    tv = talent_version(talent_id)
    confirmed = get_success_data(
        api_client.confirm_booking(
            base["booking"]["id"], f.confirm_payload(tv), AGENT
        )
    )
    base["booking"] = confirmed
    return base


def setup_completed_booking(complete_clock="2026-03-20T00:00:00Z", **kwargs):
    """Confirmed booking advanced to COMPLETED after moving the logical clock to or
    past end_date. Returns dict with booking in COMPLETED."""
    base = setup_confirmed_booking(**kwargs)
    set_clock(complete_clock)
    completed = get_success_data(
        api_client.complete_booking(base["booking"]["id"], AGENT)
    )
    base["booking"] = completed
    return base


def setup_paid_booking(gross_amount_cents=1000000, complete_clock="2026-03-20T00:00:00Z",
                       **kwargs):
    """Completed booking with a posted payment (booking PAID). Returns dict with
    booking (re-read PAID) and payment."""
    base = setup_completed_booking(complete_clock=complete_clock, **kwargs)
    payment = get_success_data(
        api_client.create_payment(
            f.create_payment_payload(
                base["booking"]["id"], base["talent"]["id"], gross_amount_cents
            ),
            AGENT,
        )
    )
    base["payment"] = payment
    base["booking"] = get_success_data(
        api_client.get_booking(base["booking"]["id"], AGENT)
    )
    return base


# ─── Submission / scheduling building blocks ──────────
def setup_open_call_with_submission(media_type="DIGITAL", usage_term_months=6,
                                    shoot_start_date="2026-05-01T00:00:00Z",
                                    shoot_end_date="2026-05-02T00:00:00Z",
                                    offered_day_rate_cents=120000,
                                    roster=False):
    """Agency + talent (comp card) + casting director + OPEN casting call + a
    SUBMITTED submission. roster=True rosters the talent first.

    Returns dict with agency, cd, talent, comp_card, call, submission.
    """
    agency = create_agency()
    cd = create_casting_director()
    talent = create_talent(agency["id"])
    comp_card = create_comp_card(talent["id"])
    if roster:
        roster_talent(talent["id"])
    call = create_casting_call(
        cd["id"], media_type=media_type, usage_term_months=usage_term_months,
        shoot_start_date=shoot_start_date, shoot_end_date=shoot_end_date,
        offered_day_rate_cents=offered_day_rate_cents,
    )
    submission = create_submission(call["id"], talent["id"], comp_card["id"])
    return {
        "agency": agency, "cd": cd, "talent": talent, "comp_card": comp_card,
        "call": call, "submission": submission,
    }


def schedule_audition_slot(cd_id, submission_id, start_at="2026-04-10T10:00:00Z",
                           end_at="2026-04-10T10:30:00Z", slot_kind="AUDITION"):
    cd_headers = make_casting_director_headers(cd_id)
    resp = api_client.create_audition_slot(
        f.create_audition_slot_payload(
            submission_id, cd_id, slot_kind=slot_kind, start_at=start_at, end_at=end_at
        ),
        cd_headers,
    )
    return get_success_data(resp)


# ─── Deal-memo negotiation building block ─────────────
def setup_offered_deal_memo(union_status="NON_UNION", media_type="PRINT",
                            usage_term_months=6, offer_day_rate_cents=150000,
                            shoot_start_date="2026-04-01T00:00:00Z",
                            shoot_end_date="2026-04-02T00:00:00Z"):
    """Roster a talent, open a call, submit, open a deal memo and extend the first
    offer (status OFFERED, round_count==1). Returns dict with agency, cd, talent,
    comp_card, call, submission, deal_memo and the cd_headers / talent_headers.
    """
    base = setup_rostered_talent(union_status=union_status)
    cd_id, talent_id, cc_id = base["cd"]["id"], base["talent"]["id"], base["comp_card"]["id"]
    cd_headers = make_casting_director_headers(cd_id)
    talent_headers = make_talent_headers(talent_id)
    call = create_casting_call(
        cd_id, media_type=media_type, usage_term_months=usage_term_months,
        shoot_start_date=shoot_start_date, shoot_end_date=shoot_end_date,
        offered_day_rate_cents=offer_day_rate_cents,
    )
    submission = create_submission(call["id"], talent_id, cc_id)
    # Advance the submission to AUDITION_SCHEDULED so opening the deal memo can move
    # it to OFFER_EXTENDED (PRD §3.5).
    schedule_audition_slot(cd_id, submission["id"])
    dm = get_success_data(
        api_client.create_deal_memo(
            f.create_deal_memo_payload(call["id"], talent_id, submission["id"]),
            cd_headers,
        )
    )
    deal_memo = get_success_data(
        api_client.offer_deal_memo(
            dm["id"],
            f.offer_payload(offer_day_rate_cents=offer_day_rate_cents,
                            offer_usage_term_months=usage_term_months),
            cd_headers,
        )
    )
    base.update({
        "call": call, "submission": submission, "deal_memo": deal_memo,
        "cd_headers": cd_headers, "talent_headers": talent_headers,
    })
    return base
