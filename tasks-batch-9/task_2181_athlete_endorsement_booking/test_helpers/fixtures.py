"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only; the database is empty at the start of each test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from . import factories as f
from .test_users import (
    ENFORCEMENT_OFFICER_ID,
    FINANCE_MANAGER_ID,
    REVIEWING_OFFICER_ID,
    SCREENING_OFFICER_ID,
    SECOND_SCREENING_OFFICER_ID,
    TEST_USERS,
    make_athlete_headers,
    make_brand_rep_headers,
    make_compliance_officer_headers,
    make_finance_manager_headers,
)

AGENT = TEST_USERS["talent_agent_headers"]


# ── Tier 0: single-call primitives ───────────────────────────────────────────

def set_clock(to_iso8601: str = DEFAULT_CLOCK_UTC, headers=None) -> dict:
    """Pin the logical clock. Before this is ever called it reads 2026-08-01T00:00:00Z."""
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, headers or AGENT)
    )


def register_athlete(**overrides) -> dict:
    return get_success_data(
        api_client.create_athlete(f.create_athlete_payload(**overrides), AGENT)
    )


def set_athlete_status(athlete_id: str, status: str, reason=None, officer_id=ENFORCEMENT_OFFICER_ID) -> dict:
    return get_success_data(
        api_client.set_athlete_status(
            athlete_id,
            f.set_athlete_status_payload(status, reason),
            make_compliance_officer_headers(officer_id),
        )
    )


def register_brand(**overrides) -> dict:
    """The minted brand id is the X-User-ID its representative acts under."""
    return get_success_data(
        api_client.create_brand(f.create_brand_payload(**overrides), TEST_USERS["brand_rep_headers"])
    )


def sanction_brand(brand_id: str, sanctioned: bool, reason=None, officer_id=ENFORCEMENT_OFFICER_ID) -> dict:
    return get_success_data(
        api_client.sanction_brand(
            brand_id,
            f.sanction_brand_payload(sanctioned, reason),
            make_compliance_officer_headers(officer_id),
        )
    )


def file_opportunity(athlete_id: str, brand_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_opportunity(
            f.create_opportunity_payload(athlete_id, brand_id, **overrides),
            make_brand_rep_headers(brand_id),
        )
    )


def screen_opportunity(opportunity_id: str, officer_id: str = SCREENING_OFFICER_ID) -> dict:
    return get_success_data(
        api_client.screen_opportunity(
            opportunity_id, make_compliance_officer_headers(officer_id)
        )
    )


def draft_term_sheet(opportunity_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_term_sheet(
            f.create_term_sheet_payload(opportunity_id, **overrides), AGENT
        )
    )


def submit_term_sheet(term_sheet_id: str) -> dict:
    return get_success_data(api_client.submit_term_sheet(term_sheet_id, AGENT))


def counter_term_sheet(term_sheet_id: str, brand_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.counter_term_sheet(
            term_sheet_id,
            f.counter_term_sheet_payload(**overrides),
            make_brand_rep_headers(brand_id),
        )
    )


def revise_term_sheet(term_sheet_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.revise_term_sheet(
            term_sheet_id, f.revise_term_sheet_payload(**overrides), AGENT
        )
    )


def accept_term_sheet(term_sheet_id: str, brand_id: str) -> dict:
    """Accepting mints the engagement; the returned row is the engagement."""
    return get_success_data(
        api_client.accept_term_sheet(term_sheet_id, make_brand_rep_headers(brand_id))
    )


def withdraw_term_sheet(term_sheet_id: str, reason=None) -> dict:
    payload = {} if reason is None else {"reason": reason}
    return get_success_data(api_client.withdraw_term_sheet(term_sheet_id, payload, AGENT))


def read_engagement(engagement_id: str) -> dict:
    return get_success_data(api_client.get_engagement(engagement_id, AGENT))


def engagement_version(engagement_id: str) -> int:
    """The engagement version an optimistic-concurrency writer must present."""
    return read_engagement(engagement_id)["version"]


def countersign_engagement(engagement_id: str, signed_by_reference=None,
                           user_id: str = FINANCE_MANAGER_ID) -> dict:
    return get_success_data(
        api_client.countersign_engagement(
            engagement_id,
            f.countersign_payload(signed_by_reference),
            make_finance_manager_headers(user_id),
        )
    )


def terminate_engagement(engagement_id: str, reason_code="MORALS_BREACH",
                         officer_id: str = ENFORCEMENT_OFFICER_ID) -> dict:
    return get_success_data(
        api_client.terminate_engagement(
            engagement_id,
            f.terminate_payload(reason_code),
            make_compliance_officer_headers(officer_id),
        )
    )


def place_booking(engagement_id: str, expected_engagement_version=None, **overrides) -> dict:
    """Place an appearance hold, refreshing the engagement version by default."""
    if expected_engagement_version is None:
        expected_engagement_version = engagement_version(engagement_id)
    return get_success_data(
        api_client.create_appearance_booking(
            f.create_appearance_booking_payload(
                engagement_id, expected_engagement_version, **overrides
            ),
            AGENT,
        )
    )


def confirm_booking(booking_id: str, travel_cost_cents=None) -> dict:
    return get_success_data(
        api_client.confirm_appearance_booking(
            booking_id, f.confirm_booking_payload(travel_cost_cents), AGENT
        )
    )


def close_booking(booking_id: str, outcome: str) -> dict:
    return get_success_data(
        api_client.close_appearance_booking(
            booking_id, f.close_booking_payload(outcome), AGENT
        )
    )


def cancel_booking(booking_id: str, reason_code="VENUE_CLOSED", headers=None) -> dict:
    return get_success_data(
        api_client.cancel_appearance_booking(
            booking_id, f.cancel_booking_payload(reason_code), headers or AGENT
        )
    )


def open_production_slot(**overrides) -> dict:
    return get_success_data(
        api_client.create_production_slot(f.create_production_slot_payload(**overrides), AGENT)
    )


def schedule_deliverable(engagement_id: str, type_: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_deliverable(
            f.create_deliverable_payload(engagement_id, type_, **overrides), AGENT
        )
    )


def submit_deliverable(deliverable_id: str, athlete_id: str, asset_url=None) -> dict:
    return get_success_data(
        api_client.submit_deliverable(
            deliverable_id,
            f.submit_deliverable_payload(asset_url),
            make_athlete_headers(athlete_id),
        )
    )


def review_deliverable(deliverable_id: str, brand_id: str, decision: str, revision_note=None) -> dict:
    return get_success_data(
        api_client.review_deliverable(
            deliverable_id,
            f.review_deliverable_payload(decision, revision_note),
            make_brand_rep_headers(brand_id),
        )
    )


def file_disclosure(deliverable_id: str, athlete_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_disclosure_record(
            f.create_disclosure_record_payload(deliverable_id, **overrides),
            make_athlete_headers(athlete_id),
        )
    )


def rule_disclosure(disclosure_id: str, ruling: str, officer_id: str = REVIEWING_OFFICER_ID,
                    finding_note=None) -> dict:
    return get_success_data(
        api_client.rule_disclosure_record(
            disclosure_id,
            f.rule_disclosure_payload(ruling, finding_note),
            make_compliance_officer_headers(officer_id),
        )
    )


def remediate_disclosure(disclosure_id: str, athlete_id: str, disclosure_tag: str,
                         posted_at: str) -> dict:
    return get_success_data(
        api_client.remediate_disclosure_record(
            disclosure_id,
            f.remediate_disclosure_payload(disclosure_tag, posted_at),
            make_athlete_headers(athlete_id),
        )
    )


def build_payout_statement(engagement_id: str, expected_engagement_version=None) -> dict:
    if expected_engagement_version is None:
        expected_engagement_version = engagement_version(engagement_id)
    return get_success_data(
        api_client.create_payout_statement(
            f.create_payout_statement_payload(engagement_id, expected_engagement_version),
            make_finance_manager_headers(),
        )
    )


def disburse_payout_statement(payout_id: str) -> dict:
    return get_success_data(
        api_client.disburse_payout_statement(payout_id, make_finance_manager_headers())
    )


def open_renewal_option(engagement_id: str, option_deadline_date: str,
                        proposed_base_fee_cents: int) -> dict:
    return get_success_data(
        api_client.create_renewal_option(
            f.create_renewal_option_payload(
                engagement_id, option_deadline_date, proposed_base_fee_cents
            ),
            AGENT,
        )
    )


def decide_renewal_option(renewal_id: str, brand_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.decide_renewal_option(
            renewal_id, f.decide_renewal_payload(decision), make_brand_rep_headers(brand_id)
        )
    )


# ── Tier 1-3: the desk chain, from roster to a live engagement ───────────────

DEAL_STAGES = ("filed", "screened", "drafted", "submitted", "pending", "active")


def build_deal(stage: str = "active",
               clock=DEFAULT_CLOCK_UTC,
               athlete: dict = None,
               athlete_overrides: dict = None,
               brand_overrides: dict = None,
               opportunity_overrides: dict = None,
               term_sheet_overrides: dict = None,
               screening_officer: str = SCREENING_OFFICER_ID,
               signed_by_reference: str = None) -> dict:
    """Walk the desk chain roster -> brand -> opportunity -> paper -> engagement.

    stage:
      "filed"     an INTAKE opportunity
      "screened"  the opportunity has been screened
      "drafted"   a DRAFT term sheet exists
      "submitted" the paper is SUBMITTED and priced
      "pending"   the paper was accepted: engagement PENDING_COUNTERSIGN
      "active"    the engagement has been countersigned

    Pass ``clock=None`` to leave the logical clock at its untouched default.
    Pass ``athlete=`` to hang a second deal off an athlete that already exists.
    """
    assert stage in DEAL_STAGES, f"unknown deal stage {stage}"
    if clock is not None:
        set_clock(clock)

    athlete = athlete or register_athlete(**(athlete_overrides or {}))
    brand = register_brand(**(brand_overrides or {}))
    opportunity = file_opportunity(
        athlete["id"], brand["id"], **(opportunity_overrides or {})
    )

    deal = {
        "athlete": athlete,
        "brand": brand,
        "opportunity": opportunity,
        "term_sheet": None,
        "engagement": None,
        "athlete_id": athlete["id"],
        "brand_id": brand["id"],
        "opportunity_id": opportunity["id"],
        "term_sheet_id": None,
        "engagement_id": None,
        "athlete_headers": make_athlete_headers(athlete["id"]),
        "brand_headers": make_brand_rep_headers(brand["id"]),
        "screening_officer": screening_officer,
    }
    if stage == "filed":
        return deal

    deal["opportunity"] = screen_opportunity(opportunity["id"], screening_officer)
    if stage == "screened":
        return deal

    term_sheet = draft_term_sheet(opportunity["id"], **(term_sheet_overrides or {}))
    deal["term_sheet"] = term_sheet
    deal["term_sheet_id"] = term_sheet["id"]
    if stage == "drafted":
        return deal

    deal["term_sheet"] = submit_term_sheet(term_sheet["id"])
    if stage == "submitted":
        return deal

    engagement = accept_term_sheet(term_sheet["id"], brand["id"])
    deal["engagement"] = engagement
    deal["engagement_id"] = engagement["id"]
    if stage == "pending":
        return deal

    deal["engagement"] = countersign_engagement(engagement["id"], signed_by_reference)
    return deal


def refresh_engagement(deal: dict) -> dict:
    """Re-read the engagement into the deal and return it."""
    deal["engagement"] = read_engagement(deal["engagement_id"])
    return deal["engagement"]


def approve_deliverable(deal: dict, type_: str = "SOCIAL_POST", asset_url=None, **overrides) -> dict:
    """Schedule a deliverable, submit the asset and approve it in one step."""
    overrides.setdefault("disclosure_required", False)
    deliverable = schedule_deliverable(deal["engagement_id"], type_, **overrides)
    submit_deliverable(deliverable["id"], deal["athlete_id"], asset_url)
    return review_deliverable(deliverable["id"], deal["brand_id"], "APPROVE")


def setup_completed_engagement(deal: dict = None, **build_kwargs) -> dict:
    """One approved SOCIAL_POST closes a one-deliverable engagement, moving the
    contract dimension to COMPLETED and the money dimension to BILLABLE."""
    deal = deal if deal is not None else build_deal(stage="active", **build_kwargs)
    deal["deliverable"] = approve_deliverable(deal)
    refresh_engagement(deal)
    return deal


def setup_invoiced_engagement(deal: dict = None, **build_kwargs) -> dict:
    """A completed engagement carrying one DRAFT payout statement."""
    deal = setup_completed_engagement(deal, **build_kwargs)
    deal["payout_statement"] = build_payout_statement(deal["engagement_id"])
    refresh_engagement(deal)
    return deal


# ── Tier 4: threshold and accumulation targeting ─────────────────────────────

FOUR_LINE_OPPORTUNITY = {
    "proposed_fee_cents": 800_000,
    "planned_posts": 2,
    "planned_appearances": 1,
    "planned_shoots": 1,
}


def setup_four_line_engagement(approve_upto: int = 4) -> dict:
    """The four-line desk scenario used for the payout waterfall.

    Two SOCIAL_POSTs, one APPEARANCE against a confirmed booking and one SHOOT
    on a capacity-1 slot; the engagement is countersigned after the booking is
    confirmed so its binding fee folds in the travel component. ``approve_upto``
    controls how many of the four lines are reviewed APPROVE.
    """
    deal = build_deal(
        stage="pending",
        opportunity_overrides=dict(FOUR_LINE_OPPORTUNITY),
        term_sheet_overrides={"appearance_days": 2},
    )
    booking = place_booking(
        deal["engagement_id"],
        city="Chicago",
        start_at="2026-09-10T14:00:00Z",
        end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=12,
    )
    confirm_booking(booking["id"], 180_500)
    deal["booking"] = booking
    deal["engagement"] = countersign_engagement(deal["engagement_id"])

    slot = open_production_slot()
    deal["slot"] = slot

    deliverables = [
        schedule_deliverable(deal["engagement_id"], "SOCIAL_POST",
                             due_date="2026-09-20", disclosure_required=False),
        schedule_deliverable(deal["engagement_id"], "SOCIAL_POST",
                             due_date="2026-09-21", disclosure_required=False),
        schedule_deliverable(deal["engagement_id"], "APPEARANCE",
                             due_date="2026-09-11", disclosure_required=False,
                             booking_id=booking["id"]),
        schedule_deliverable(deal["engagement_id"], "SHOOT",
                             due_date="2026-09-16", disclosure_required=False,
                             production_slot_id=slot["id"],
                             shoot_start_at="2026-09-15T09:00:00Z",
                             shoot_end_at="2026-09-15T13:00:00Z"),
    ]
    for index, deliverable in enumerate(deliverables):
        submit_deliverable(deliverable["id"], deal["athlete_id"],
                           f"https://cdn.example/a{index + 1}.jpg")
    for deliverable in deliverables[:approve_upto]:
        review_deliverable(deliverable["id"], deal["brand_id"], "APPROVE")

    deal["deliverables"] = [
        get_success_data(api_client.get_deliverable(d["id"], AGENT)) for d in deliverables
    ]
    refresh_engagement(deal)
    return deal


def setup_deliverable_awaiting_disclosure(deal: dict = None, disclosure_tag: str = "#sp",
                                          platform: str = "INSTAGRAM",
                                          **build_kwargs) -> dict:
    """A SUBMITTED deliverable that requires disclosure, plus a filed record.

    ``platform`` names the publication surface the record carries; it is a
    disclosure-record field, not a deal-building one, so it is forwarded to the
    filing call rather than into ``build_deal``.
    """
    deal = deal if deal is not None else build_deal(stage="active", **build_kwargs)
    deliverable = schedule_deliverable(
        deal["engagement_id"], "SOCIAL_POST", due_date="2026-09-20", disclosure_required=True
    )
    submit_deliverable(deliverable["id"], deal["athlete_id"], "https://cdn.example/post1.jpg")
    record = file_disclosure(
        deliverable["id"], deal["athlete_id"],
        disclosure_tag=disclosure_tag, platform=platform,
    )
    deal["deliverable"] = deliverable
    deal["disclosure_record"] = record
    return deal


def setup_two_engagement_athlete() -> dict:
    """One athlete carrying two countersigned engagements in different
    categories: BEVERAGE at TIER_B and FOOTWEAR at TIER_C."""
    deal_a = build_deal(
        stage="active",
        opportunity_overrides=dict(FOUR_LINE_OPPORTUNITY),
        term_sheet_overrides={"appearance_days": 2},
        signed_by_reference="CS-2026-0006",
    )
    deal_b = build_deal(
        stage="active",
        clock=None,
        athlete=deal_a["athlete"],
        brand_overrides={
            "name": "Kite Footwear",
            "category": "FOOTWEAR",
            "legal_entity_name": "Kite Footwear LLC",
        },
        opportunity_overrides={
            "exclusivity_category": "FOOTWEAR",
            "exclusivity_months": 6,
            "territory": "DOMESTIC",
            "usage_rights_tier": "SOCIAL_ONLY",
        },
        term_sheet_overrides={
            "fee_cents": 1_000_000,
            "usage_rights_tier": "SOCIAL_ONLY",
            "territory": "DOMESTIC",
            "morals_clause_tier": "TIER_C",
            "exclusivity_months": 6,
            "appearance_days": 0,
        },
        screening_officer=SECOND_SCREENING_OFFICER_ID,
        signed_by_reference="CS-2026-0007",
    )
    return {"deal_a": deal_a, "deal_b": deal_b, "athlete": deal_a["athlete"]}


def setup_terminated_engagement_over_busy_calendar() -> dict:
    """One athlete, two engagements. The FOOTWEAR engagement holds a CONFIRMED
    booking that pads the calendar to 2026-09-11T10:00Z; the BEVERAGE engagement
    has been terminated, so a booking against it violates both the contract-status
    rule and the calendar rule at once."""
    pair = setup_two_engagement_athlete()
    booking = place_booking(
        pair["deal_b"]["engagement_id"],
        city="Denver",
        start_at="2026-09-10T14:00:00Z",
        end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=12,
    )
    confirm_booking(booking["id"], 50_000)
    terminate_engagement(pair["deal_a"]["engagement_id"], reason_code="BRAND_WITHDRAWAL")
    pair["booking"] = booking
    return pair


def setup_exposure_scenario() -> dict:
    """One athlete with a countersigned TIER_B BEVERAGE engagement (one ACTIVE
    grant) and, in flight, a SUBMITTED TIER_A FOOTWEAR term sheet on a second
    opportunity that names the same athlete."""
    committed = build_deal(
        stage="active",
        opportunity_overrides=dict(FOUR_LINE_OPPORTUNITY),
        term_sheet_overrides={"appearance_days": 2},
    )
    in_flight = build_deal(
        stage="submitted",
        clock=None,
        athlete=committed["athlete"],
        brand_overrides={
            "name": "Kite Footwear",
            "category": "FOOTWEAR",
            "legal_entity_name": "Kite Footwear LLC",
        },
        opportunity_overrides={
            "exclusivity_category": "FOOTWEAR",
            "exclusivity_months": 6,
            "territory": "DOMESTIC",
            "usage_rights_tier": "SOCIAL_ONLY",
        },
        term_sheet_overrides={
            "fee_cents": 1_000_000,
            "usage_rights_tier": "SOCIAL_ONLY",
            "territory": "DOMESTIC",
            "morals_clause_tier": "TIER_A",
            "exclusivity_months": 6,
            "appearance_days": 0,
        },
        screening_officer=SECOND_SCREENING_OFFICER_ID,
    )
    return {
        "committed": committed,
        "in_flight": in_flight,
        "athlete": committed["athlete"],
        "athlete_id": committed["athlete_id"],
    }


def setup_engagement_with_confirmed_booking(travel_cost_cents: int = 180_500) -> dict:
    """A PENDING_COUNTERSIGN engagement carrying exactly one CONFIRMED booking:
    an 8-hour appearance padded by a 12-hour travel buffer on each side."""
    deal = build_deal(
        stage="pending",
        opportunity_overrides=dict(FOUR_LINE_OPPORTUNITY),
        term_sheet_overrides={"appearance_days": 2},
    )
    booking = place_booking(
        deal["engagement_id"],
        city="Chicago",
        start_at="2026-09-10T14:00:00Z",
        end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=12,
    )
    deal["booking"] = confirm_booking(booking["id"], travel_cost_cents)
    refresh_engagement(deal)
    return deal


def setup_engagement_ready_for_unwind() -> dict:
    """An ACTIVE engagement holding everything the termination unwind touches: an
    ACTIVE exclusivity grant, a CONFIRMED booking with its travel accrual and a
    PENDING SHOOT deliverable reserving a capacity-1 production slot."""
    deal = setup_engagement_with_confirmed_booking()
    deal["engagement"] = countersign_engagement(deal["engagement_id"])
    slot = open_production_slot()
    shoot = schedule_deliverable(
        deal["engagement_id"], "SHOOT", due_date="2026-09-16", disclosure_required=False,
        production_slot_id=slot["id"],
        shoot_start_at="2026-09-15T09:00:00Z", shoot_end_at="2026-09-15T13:00:00Z",
    )
    deal["slot"] = slot
    deal["shoot"] = shoot
    return deal
