"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints (the harness restarts the server before each test, so the database
is always empty at test start). Setup calls use get_success_data so a setup
failure surfaces as a clear error rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    activate_payload,
    clock_payload,
    create_agreement_payload,
    create_amenity_payload,
    create_application_payload,
    create_budget_payload,
    create_builder_payload,
    create_closing_payload,
    create_community_payload,
    create_district_payload,
    create_advance_payload,
    create_event_payload,
    create_levy_payload,
    create_line_item_payload,
    create_lot_payload,
    create_notice_payload,
    create_payment_payload,
    create_phase_payload,
    create_resident_payload,
    create_tranche_payload,
    create_violation_payload,
)
from .test_users import (
    TEST_USERS,
    make_builder_rep_headers,
    make_design_reviewer_headers,
    make_homeowner_resident_headers,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]
REVIEWER = TEST_USERS["design_reviewer_headers"]
LIFESTYLE = TEST_USERS["lifestyle_coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------- clock ----
def set_clock(to_iso8601: str):
    """Advance the logical clock (runs the server sweep)."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


# ------------------------------------------------------------ community ----
def create_community(name="Test Community", total_planned_units=100):
    """Create a PLANNING community. Returns the community dict."""
    return get_success_data(
        api_client.create_community(
            create_community_payload(community_name=name, total_planned_units=total_planned_units),
            EXEC,
        )
    )


def create_active_community(name="Test Community", total_planned_units=100):
    """Create a community and activate it (seats the 5-member declarant board)."""
    community = create_community(name, total_planned_units)
    get_success_data(api_client.activate_community(community["id"], activate_payload(), EXEC))
    community["status"] = "ACTIVE"
    return community


def create_phase(community_id, phase_name="P1", sequence_no=1, planned_lot_count=10):
    return get_success_data(
        api_client.create_phase(
            create_phase_payload(
                community_id=community_id,
                phase_name=phase_name,
                sequence_no=sequence_no,
                planned_lot_count=planned_lot_count,
            ),
            EXEC,
        )
    )


def create_open_phase(community_id, phase_name="P1", sequence_no=1, planned_lot_count=10):
    """Create a phase in an ACTIVE community and open it for sales."""
    phase = create_phase(community_id, phase_name, sequence_no, planned_lot_count)
    get_success_data(api_client.open_sales(phase["id"], EXEC))
    phase["status"] = "SALES_OPEN"
    return phase


def create_builder(community_id, legal_name="Builder Co", credit_tier="A"):
    return get_success_data(
        api_client.create_builder(
            create_builder_payload(
                community_id=community_id, legal_name=legal_name, credit_tier=credit_tier
            ),
            EXEC,
        )
    )


# ---------------------------------------------------------- agreements -----
def create_draft_agreement(
    community_id,
    builder_id,
    phase_id,
    total_lots_committed=1,
    tranches=None,
    **agreement_overrides,
):
    """Create a DRAFT agreement plus its tranche schedule.

    tranches: list of (due_date, lot_count_due) tuples. Defaults to a single
    tranche covering the full commitment, due 2026-06-30.
    Returns (agreement, [tranche, ...]).
    """
    agreement = get_success_data(
        api_client.create_agreement(
            create_agreement_payload(
                community_id=community_id,
                builder_id=builder_id,
                phase_id=phase_id,
                total_lots_committed=total_lots_committed,
                **agreement_overrides,
            ),
            CTRL,
        )
    )
    if tranches is None:
        tranches = [("2026-06-30T00:00:00Z", total_lots_committed)]
    created = []
    for i, (due_date, lot_count_due) in enumerate(tranches, start=1):
        created.append(
            get_success_data(
                api_client.create_tranche(
                    create_tranche_payload(
                        agreement_id=agreement["id"],
                        tranche_no=i,
                        due_date=due_date,
                        lot_count_due=lot_count_due,
                    ),
                    CTRL,
                )
            )
        )
    return agreement, created


def create_executed_agreement(community_id, builder_id, phase_id, total_lots_committed=1,
                              tranches=None, **overrides):
    """DRAFT + tranches + execute. Returns (agreement, tranches)."""
    agreement, tranche_list = create_draft_agreement(
        community_id, builder_id, phase_id, total_lots_committed, tranches, **overrides
    )
    get_success_data(api_client.execute_agreement(agreement["id"], EXEC))
    agreement["status"] = "EXECUTED"
    return agreement, tranche_list


def create_active_agreement(community_id, builder_id, phase_id, total_lots_committed=1,
                            tranches=None, **overrides):
    """Full DRAFT -> EXECUTED -> ACTIVE path. Returns (agreement, tranches)."""
    agreement, tranche_list = create_executed_agreement(
        community_id, builder_id, phase_id, total_lots_committed, tranches, **overrides
    )
    get_success_data(api_client.commence_agreement(agreement["id"], CTRL))
    agreement["status"] = "ACTIVE"
    return agreement, tranche_list


# ---------------------------------------------------------------- lots -----
def create_lot(phase_id, parcel_number=None, **overrides):
    payload = create_lot_payload(phase_id=phase_id, **overrides)
    if parcel_number is not None:
        payload["parcel_number"] = parcel_number
    return get_success_data(api_client.create_lot(payload, EXEC))


def create_offered_lot(phase_id, parcel_number=None, **overrides):
    lot = create_lot(phase_id, parcel_number, **overrides)
    get_success_data(api_client.offer_lot(lot["id"], EXEC))
    lot["status"] = "OFFERED"
    return lot


def create_and_close_lot(agreement_id, lot_id, owner_resident_id=None):
    """Open escrow and close it. Returns the CLOSED closing dict."""
    payload = create_closing_payload(agreement_id=agreement_id, lot_id=lot_id)
    if owner_resident_id is not None:
        payload["owner_resident_id"] = owner_resident_id
    closing = get_success_data(api_client.create_closing(payload, CTRL))
    return get_success_data(api_client.close_closing(closing["id"], CTRL))


# ------------------------------------------- sales-side composite state ----
def setup_sales_community(total_planned_units=20, planned_lot_count=10, community_name="Sales Community"):
    """Active community + SALES_OPEN phase + builder. Returns (community, phase, builder)."""
    community = create_active_community(community_name, total_planned_units)
    phase = create_open_phase(community["id"], planned_lot_count=planned_lot_count)
    builder = create_builder(community["id"])
    return community, phase, builder


def setup_active_agreement_scenario(
    total_planned_units=20,
    planned_lot_count=10,
    total_lots_committed=2,
    tranches=None,
    community_name="Scenario Community",
    **agreement_overrides,
):
    """Active community + open phase + builder + ACTIVE agreement with tranches.

    Returns dict with keys: community, phase, builder, agreement, tranches.
    """
    community, phase, builder = setup_sales_community(
        total_planned_units, planned_lot_count, community_name
    )
    agreement, tranche_list = create_active_agreement(
        community["id"],
        builder["id"],
        phase["id"],
        total_lots_committed,
        tranches,
        **agreement_overrides,
    )
    return {
        "community": community,
        "phase": phase,
        "builder": builder,
        "agreement": agreement,
        "tranches": tranche_list,
    }


def setup_missed_tranche_scenario(
    total_lots_committed=2,
    tranches=(("2026-06-30T00:00:00Z", 1), ("2026-12-31T00:00:00Z", 1)),
    community_name="Missed Community",
    **agreement_overrides,
):
    """ACTIVE agreement whose first tranche is MISSED (builder PROBATION).

    Clock is left at 2026-07-01. Returns the scenario dict.
    """
    scenario = setup_active_agreement_scenario(
        total_lots_committed=total_lots_committed,
        tranches=list(tranches),
        community_name=community_name,
        **agreement_overrides,
    )
    set_clock("2026-06-01T00:00:00Z")
    set_clock("2026-07-01T00:00:00Z")
    return scenario


# -------------------------------------------------------------- budgets ----
def create_proposed_budget(community_id, fiscal_year=2027, line_items=None,
                           non_assessment_income_cents=None):
    """DRAFT budget + line items + propose. Returns the budget dict.

    line_items: list of (category, amount_cents) or (category, amount_cents, is_reserve).
    """
    payload = create_budget_payload(community_id=community_id, fiscal_year=fiscal_year)
    if non_assessment_income_cents is not None:
        payload["non_assessment_income_cents"] = non_assessment_income_cents
    budget = get_success_data(api_client.create_budget(payload, CTRL))
    if line_items is None:
        line_items = [("MANAGEMENT", 100000)]
    for item in line_items:
        category, amount = item[0], item[1]
        extra = {"is_reserve": item[2]} if len(item) > 2 else {}
        get_success_data(
            api_client.create_line_item(
                create_line_item_payload(
                    budget_id=budget["id"], category=category, amount_cents=amount, **extra
                ),
                CTRL,
            )
        )
    get_success_data(api_client.propose_budget(budget["id"], CTRL))
    budget["status"] = "PROPOSED"
    return budget


def create_and_schedule_notice(community_id, notice_type, send_at, **links):
    """DRAFT notice -> SCHEDULED. Returns the notice dict."""
    payload = create_notice_payload(
        community_id=community_id, notice_type=notice_type, send_at=send_at, **links
    )
    notice = get_success_data(api_client.create_notice(payload, LIFESTYLE))
    get_success_data(api_client.schedule_notice(notice["id"], LIFESTYLE))
    notice["status"] = "SCHEDULED"
    return notice


def create_sent_notice(community_id, notice_type, send_at, **links):
    """Schedule a notice and sweep the clock so it is SENT (sent_at == send_at).

    Leaves the logical clock at send_at.
    """
    notice = create_and_schedule_notice(community_id, notice_type, send_at, **links)
    set_clock(send_at)
    notice["status"] = "SENT"
    notice["sent_at"] = send_at
    return notice


def create_adopted_budget(community_id, fiscal_year=2027, line_items=None,
                          non_assessment_income_cents=None,
                          notice_send_at="2026-05-02T00:00:00Z",
                          adopt_at="2026-05-17T00:00:00Z"):
    """Full budget adoption at DECLARANT_CONTROL: propose, SENT notice, adopt.

    Leaves the logical clock at adopt_at. Returns the ADOPTED budget dict.
    """
    budget = create_proposed_budget(
        community_id, fiscal_year, line_items, non_assessment_income_cents
    )
    create_and_schedule_notice(
        community_id, "BUDGET_ADOPTION", notice_send_at, budget_id=budget["id"],
        subject=f"FY{fiscal_year} adoption", body="adoption",
    )
    set_clock(notice_send_at)
    set_clock(adopt_at)
    adopted = get_success_data(api_client.adopt_budget(budget["id"], DIRECTOR))
    return adopted


def create_effective_rate(community_id, fiscal_year=2027, budget_line_items=None,
                          non_assessment_income_cents=None,
                          notice_send_at=None, adopt_at=None):
    """ADOPTED budget + CALCULATED rate + ASSESSMENT_CHANGE notice + arm +
    sweep past fiscal-year start so the rate is EFFECTIVE.

    Standard timeline: adoption notice SENT 2026-05-02, adopt 2026-05-17,
    rate notice SENT {fy-1}-11-01, arm {fy-1}-11-02, sweep to {fy}-01-01.
    Returns (rate, budget).

    notice_send_at / adopt_at override the budget-adoption timeline so
    callers can chain multiple rate setups on a single monotonic clock.
    """
    budget_kwargs = {}
    if notice_send_at is not None:
        budget_kwargs["notice_send_at"] = notice_send_at
    if adopt_at is not None:
        budget_kwargs["adopt_at"] = adopt_at
    budget = create_adopted_budget(
        community_id, fiscal_year, budget_line_items, non_assessment_income_cents,
        **budget_kwargs,
    )
    rate = get_success_data(
        api_client.create_assessment_rate(
            {"community_id": community_id, "budget_id": budget["id"], "fiscal_year": fiscal_year},
            CTRL,
        )
    )
    prior_year = fiscal_year - 1
    create_and_schedule_notice(
        community_id, "ASSESSMENT_CHANGE", f"{prior_year}-11-01T00:00:00Z",
        assessment_rate_id=rate["id"], subject=f"FY{fiscal_year} rate", body="rate",
        effective_date=f"{fiscal_year}-01-01T00:00:00Z",
    )
    set_clock(f"{prior_year}-11-02T00:00:00Z")
    get_success_data(api_client.arm_rate(rate["id"], CTRL))
    set_clock(f"{fiscal_year}-01-01T00:00:00Z")
    rate = get_success_data(api_client.get_assessment_rate(rate["id"], CTRL))
    return rate, budget


# ------------------------------------------------------------- district ----
def create_district_with_advances(community_id, advances, district_name="MUD 1",
                                  interest_rate_annual_pct=5.0):
    """District plus recorded advances. advances: list of (amount_cents, advance_date).
    Returns (district, [advance, ...])."""
    district = get_success_data(
        api_client.create_district(
            create_district_payload(
                community_id=community_id,
                district_name=district_name,
                interest_rate_annual_pct=interest_rate_annual_pct,
            ),
            CTRL,
        )
    )
    created = []
    for amount, date in advances:
        created.append(
            get_success_data(
                api_client.create_advance(
                    create_advance_payload(
                        district_id=district["id"], amount_cents=amount, advance_date=date
                    ),
                    CTRL,
                )
            )
        )
    return district, created


def create_funded_district(community_id, advances, levy_amount_cents, levy_year=2026,
                           **district_overrides):
    """District + advances + a COLLECTED levy. Returns (district, advances, levy)."""
    district, advance_list = create_district_with_advances(
        community_id, advances, **district_overrides
    )
    levy = get_success_data(
        api_client.create_levy(
            create_levy_payload(
                district_id=district["id"], levy_year=levy_year, amount_cents=levy_amount_cents
            ),
            CTRL,
        )
    )
    get_success_data(api_client.collect_levy(levy["id"], CTRL))
    levy["status"] = "COLLECTED"
    return district, advance_list, levy


def create_requested_payment(district_id, amount_cents):
    return get_success_data(
        api_client.create_payment(
            create_payment_payload(district_id=district_id, amount_cents=amount_cents), CTRL
        )
    )


def create_certified_payment(district_id, amount_cents):
    payment = create_requested_payment(district_id, amount_cents)
    return get_success_data(api_client.certify_payment(payment["id"], DIRECTOR))


# ------------------------------------------------------------- amenities ---
def create_amenity(community_id, amenity_type="CLUBHOUSE", **overrides):
    return get_success_data(
        api_client.create_amenity(
            create_amenity_payload(
                community_id=community_id, amenity_type=amenity_type, **overrides
            ),
            EXEC,
        )
    )


def create_amenity_in_state(community_id, target_state, amenity_type="CLUBHOUSE", **overrides):
    """Walk an amenity to IN_DESIGN / UNDER_CONSTRUCTION / OPEN."""
    amenity = create_amenity(community_id, amenity_type, **overrides)
    if target_state in ("IN_DESIGN", "UNDER_CONSTRUCTION", "OPEN"):
        get_success_data(api_client.start_design(amenity["id"], EXEC))
    if target_state in ("UNDER_CONSTRUCTION", "OPEN"):
        get_success_data(api_client.start_construction(amenity["id"], EXEC))
    if target_state == "OPEN":
        get_success_data(api_client.open_amenity(amenity["id"], EXEC))
    amenity["status"] = target_state
    return amenity


# --------------------------------------------------------------- events ----
def create_scheduled_event(community_id, title="Event", venue="SALES_CENTER",
                           start_at="2026-05-20T10:00:00Z", end_at="2026-05-20T12:00:00Z",
                           capacity=10, cost_cents=None, charged_budget_id=None):
    """PROPOSED event -> SCHEDULED. Returns the event dict."""
    payload = create_event_payload(
        community_id=community_id, title=title, venue=venue,
        start_at=start_at, end_at=end_at, capacity=capacity,
    )
    if cost_cents is not None:
        payload["cost_cents"] = cost_cents
    if charged_budget_id is not None:
        payload["charged_budget_id"] = charged_budget_id
    event = get_success_data(api_client.create_event(payload, LIFESTYLE))
    get_success_data(api_client.schedule_event(event["id"], LIFESTYLE))
    event["status"] = "SCHEDULED"
    return event


def create_resident(community_id, full_name=None, email=None):
    payload = create_resident_payload(community_id=community_id)
    if full_name is not None:
        payload["full_name"] = full_name
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_resident(payload, LIFESTYLE))


def create_residents(community_id, names_emails):
    """Bulk-create residents. names_emails: list of (full_name, email)."""
    return [create_resident(community_id, name, email) for name, email in names_emails]


# -------------------------------------------------------- design review ----
def create_application(community_id, lot_id, applicant_builder_id=None,
                       applicant_resident_id=None, project_type="NEW_CONSTRUCTION"):
    """Submit an application as its own applicant (identity threading)."""
    payload = create_application_payload(
        community_id=community_id, lot_id=lot_id, project_type=project_type,
    )
    if applicant_builder_id is not None:
        payload["applicant_builder_id"] = applicant_builder_id
        headers = make_builder_rep_headers(applicant_builder_id)
    else:
        payload["applicant_resident_id"] = applicant_resident_id
        headers = make_homeowner_resident_headers(applicant_resident_id)
    return get_success_data(api_client.create_application(payload, headers))


def deny_round(application_id, reviewer_id, denial_reason="denied"):
    """begin-review + deny as the named reviewer."""
    reviewer_headers = make_design_reviewer_headers(reviewer_id)
    get_success_data(api_client.begin_review(application_id, reviewer_headers))
    return get_success_data(
        api_client.deny_application(application_id, {"denial_reason": denial_reason}, reviewer_headers)
    )


def resubmit_application(application_id, applicant_builder_id=None, applicant_resident_id=None):
    if applicant_builder_id is not None:
        headers = make_builder_rep_headers(applicant_builder_id)
    else:
        headers = make_homeowner_resident_headers(applicant_resident_id)
    return get_success_data(api_client.resubmit_application(application_id, headers))


# ------------------------------------------------------------ violations ---
def create_violation(community_id, lot_id, respondent_resident_id=None,
                     respondent_builder_id=None, violation_type="SETBACK"):
    payload = create_violation_payload(
        community_id=community_id, lot_id=lot_id, violation_type=violation_type,
    )
    if respondent_resident_id is not None:
        payload["respondent_resident_id"] = respondent_resident_id
    if respondent_builder_id is not None:
        payload["respondent_builder_id"] = respondent_builder_id
    return get_success_data(api_client.create_violation(payload, REVIEWER))


def create_violation_notice_sent(community_id, lot_id, **kwargs):
    """REPORTED -> NOTICE_SENT at the current clock. cure_deadline = clock + 14d."""
    violation = create_violation(community_id, lot_id, **kwargs)
    get_success_data(api_client.send_violation_notice(violation["id"], REVIEWER))
    violation["status"] = "NOTICE_SENT"
    return violation


def create_violation_hearing_scheduled(community_id, lot_id, escalate_at, hearing_date,
                                       notice_clock=None, **kwargs):
    """NOTICE_SENT -> sweep to escalate_at -> ESCALATED -> HEARING_SCHEDULED.

    The notice is sent at the current logical clock unless notice_clock is
    given, in which case the clock is first advanced to that instant. The
    clock is left at escalate_at on return.
    """
    if notice_clock is not None:
        set_clock(notice_clock)
    violation = create_violation_notice_sent(community_id, lot_id, **kwargs)
    set_clock(escalate_at)
    get_success_data(api_client.escalate_violation(violation["id"], REVIEWER))
    get_success_data(
        api_client.schedule_hearing(violation["id"], {"hearing_date": hearing_date}, DIRECTOR)
    )
    violation["status"] = "HEARING_SCHEDULED"
    return violation


# ----------------------------------------------------------- board seats ---
def list_community_seats(community_id):
    """Board seats of a community, seat_no ascending (server-documented order)."""
    resp = api_client.list_board_seats(DIRECTOR, params={"community_id": community_id})
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    return data


def fill_seat_by_election(seat_id, holder_resident_id, votes_cast=1, votes_for=1):
    """call-election + certify-election as an AssociationDirector."""
    get_success_data(api_client.call_election(seat_id, DIRECTOR))
    return get_success_data(
        api_client.certify_election(
            seat_id,
            {
                "votes_cast": votes_cast,
                "votes_for": votes_for,
                "holder_resident_id": holder_resident_id,
            },
            DIRECTOR,
        )
    )


def close_lots_with_owners(agreement_id, lot_ids, resident_ids):
    """Close each lot with the matching owner resident. Returns closings."""
    closings = []
    for lot_id, resident_id in zip(lot_ids, resident_ids):
        closings.append(create_and_close_lot(agreement_id, lot_id, resident_id))
    return closings
