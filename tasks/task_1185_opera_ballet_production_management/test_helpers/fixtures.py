"""Composite setup helpers.

Multi-step state builders so tests can focus on assertions. Every helper
creates its own entities from scratch (the server restarts before every
test) and uses get_success_data() so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_artist_payload,
    create_build_item_payload,
    create_call_participant_payload,
    create_cast_assignment_payload,
    create_contract_payload,
    create_co_production_share_payload,
    create_partner_company_payload,
    create_performance_payload,
    create_production_payload,
    create_rehearsal_call_payload,
    create_rehearsal_room_payload,
    create_rental_offer_payload,
    create_role_payload,
    create_stage_slot_payload,
    create_surtitle_track_payload,
)
from .test_users import (
    TEST_USERS,
    make_contracts_officer_headers,
    make_partner_representative_headers,
    make_production_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["production_manager_headers"]
CD = TEST_USERS["casting_director_headers"]
CO = TEST_USERS["contracts_officer_headers"]
TD = TEST_USERS["technical_director_headers"]
BOM = TEST_USERS["box_office_manager_headers"]
ANY = TEST_USERS["any_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------
def create_partner_company(name="PartnerCo", partner_kind="CO_PRODUCER") -> dict:
    resp = api_client.create_partner_company(
        create_partner_company_payload(name=name, partner_kind=partner_kind), ADMIN
    )
    return get_success_data(resp)


def set_partner_standing(company_id, to_state) -> dict:
    resp = api_client.transition_partner_company(company_id, to_state, ADMIN)
    return get_success_data(resp)


def create_production(**overrides) -> dict:
    resp = api_client.create_production(create_production_payload(**overrides), PM)
    return get_success_data(resp)


def transition_production(production_id, to_state, headers=None) -> dict:
    resp = api_client.transition_production(production_id, to_state, headers or PM)
    return get_success_data(resp)


def get_production(production_id) -> dict:
    return get_success_data(api_client.get_production(production_id, ANY))


def create_production_in_state(target_state, **overrides) -> dict:
    """Walk the production lifecycle to DESIGN, BUILD, or REHEARSAL.

    BUILD -> REHEARSAL is vacuously satisfiable with no build items (PRD §3.2).
    """
    production = create_production(**overrides)
    if target_state == "DESIGN":
        return production
    if target_state in ("BUILD", "REHEARSAL"):
        production = transition_production(production["id"], "BUILD")
        if target_state == "BUILD":
            return production
        return transition_production(production["id"], "REHEARSAL")
    raise ValueError(f"unsupported target_state for this helper: {target_state}")


def create_build_item(production_id, **overrides) -> dict:
    resp = api_client.create_build_item(
        create_build_item_payload(production_id, **overrides), PM
    )
    return get_success_data(resp)


def transition_build_item(item_id, to_state, actual_cost_cents=None) -> dict:
    resp = api_client.transition_build_item(
        item_id, to_state, PM, actual_cost_cents=actual_cost_cents
    )
    return get_success_data(resp)


def create_share(production_id, company_id, share_percentage, cost_split_method) -> dict:
    resp = api_client.create_co_production_share(
        create_co_production_share_payload(
            production_id,
            company_id,
            share_percentage=share_percentage,
            cost_split_method=cost_split_method,
        ),
        PM,
    )
    return get_success_data(resp)


def transition_share(share_id, to_state) -> dict:
    resp = api_client.transition_co_production_share(share_id, to_state, PM)
    return get_success_data(resp)


def create_artist(**overrides) -> dict:
    resp = api_client.create_artist(create_artist_payload(**overrides), CO)
    return get_success_data(resp)


def create_contract(production_id, artist_id, officer_user_id="officer-1", **overrides) -> dict:
    headers = make_contracts_officer_headers(officer_user_id)
    resp = api_client.create_contract(
        create_contract_payload(production_id, artist_id, **overrides), headers
    )
    return get_success_data(resp)


def transition_contract(contract_id, to_state, officer_user_id="officer-1") -> dict:
    headers = make_contracts_officer_headers(officer_user_id)
    resp = api_client.transition_contract(contract_id, to_state, headers)
    return get_success_data(resp)


def create_active_contract(production_id, officer_user_id="officer-1",
                           artist_overrides=None, **contract_overrides):
    """Artist + contract walked DRAFT -> OFFERED -> SIGNED -> ACTIVE.

    Activation requires the production to be in BUILD, REHEARSAL, or
    IN_REPERTORY (PRD §3.4), so callers pass a production already there.
    Returns (artist, contract).
    """
    artist = create_artist(**(artist_overrides or {}))
    contract = create_contract(
        production_id, artist["id"], officer_user_id=officer_user_id, **contract_overrides
    )
    contract = transition_contract(contract["id"], "OFFERED", officer_user_id=officer_user_id)
    contract = transition_contract(contract["id"], "SIGNED", officer_user_id=officer_user_id)
    contract = transition_contract(contract["id"], "ACTIVE", officer_user_id=officer_user_id)
    return artist, contract


def create_role(production_id, **overrides) -> dict:
    resp = api_client.create_role(create_role_payload(production_id, **overrides), CD)
    return get_success_data(resp)


def create_cast_assignment(role_id, contract_id, slot="PRINCIPAL", covers_assignment_id=None) -> dict:
    payload = create_cast_assignment_payload(
        role_id, contract_id, slot=slot, covers_assignment_id=covers_assignment_id
    )
    if covers_assignment_id is None:
        payload.pop("covers_assignment_id", None)
    resp = api_client.create_cast_assignment(payload, CD)
    return get_success_data(resp)


def confirm_cast_assignment(assignment_id) -> dict:
    return get_success_data(api_client.confirm_cast_assignment(assignment_id, CD))


def release_cast_assignment(assignment_id) -> dict:
    return get_success_data(api_client.release_cast_assignment(assignment_id, CD))


def get_cast_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_cast_assignment(assignment_id, ANY))


def get_role(role_id) -> dict:
    return get_success_data(api_client.get_role(role_id, ANY))


def create_rehearsal_room(**overrides) -> dict:
    resp = api_client.create_rehearsal_room(create_rehearsal_room_payload(**overrides), TD)
    return get_success_data(resp)


def create_rehearsal_call(production_id, room_id, starts_at, ends_at, **overrides) -> dict:
    resp = api_client.create_rehearsal_call(
        create_rehearsal_call_payload(production_id, room_id, starts_at, ends_at, **overrides),
        TD,
    )
    return get_success_data(resp)


def transition_rehearsal_call(call_id, to_state) -> dict:
    resp = api_client.transition_rehearsal_call(call_id, to_state, TD)
    return get_success_data(resp)


def create_published_call(production_id, room_id, starts_at, ends_at, **overrides) -> dict:
    call = create_rehearsal_call(production_id, room_id, starts_at, ends_at, **overrides)
    return transition_rehearsal_call(call["id"], "PUBLISHED")


def get_rehearsal_call(call_id) -> dict:
    return get_success_data(api_client.get_rehearsal_call(call_id, ANY))


def create_confirmed_participant(call_id, contract_id, officer_user_id="officer-1") -> dict:
    """Add a participant (rest floor must pass) and confirm it."""
    headers = make_contracts_officer_headers(officer_user_id)
    resp = api_client.create_call_participant(
        create_call_participant_payload(call_id, contract_id), headers
    )
    participant = get_success_data(resp)
    resp = api_client.transition_call_participant(participant["id"], "CONFIRMED", headers)
    return get_success_data(resp)


def create_stage_slot(production_id, starts_at, ends_at, **overrides) -> dict:
    resp = api_client.create_stage_slot(
        create_stage_slot_payload(production_id, starts_at, ends_at, **overrides), TD
    )
    return get_success_data(resp)


def transition_stage_slot(slot_id, to_state) -> dict:
    resp = api_client.transition_stage_slot(slot_id, to_state, TD)
    return get_success_data(resp)


def create_done_tech_slot(production_id, starts_at, ends_at) -> dict:
    slot = create_stage_slot(production_id, starts_at, ends_at, slot_type="TECH")
    slot = transition_stage_slot(slot["id"], "LOCKED")
    return transition_stage_slot(slot["id"], "DONE")


def create_surtitle_track(production_id, **overrides) -> dict:
    resp = api_client.create_surtitle_track(
        create_surtitle_track_payload(production_id, **overrides), TD
    )
    return get_success_data(resp)


def transition_surtitle_track(track_id, to_state) -> dict:
    resp = api_client.transition_surtitle_track(track_id, to_state, TD)
    return get_success_data(resp)


def create_live_surtitle_track(production_id, language="en", cue_count=400) -> dict:
    track = create_surtitle_track(production_id, language=language, cue_count=cue_count)
    track = transition_surtitle_track(track["id"], "TRANSLATED")
    track = transition_surtitle_track(track["id"], "CUES_LOCKED")
    return transition_surtitle_track(track["id"], "LIVE")


def create_performance(production_id, starts_at, ends_at, sections=None, **overrides) -> dict:
    resp = api_client.create_performance(
        create_performance_payload(production_id, starts_at, ends_at, sections=sections, **overrides),
        BOM,
    )
    return get_success_data(resp)


def open_performance_sales(performance_id) -> dict:
    return get_success_data(api_client.open_sales(performance_id, BOM))


def get_performance(performance_id) -> dict:
    return get_success_data(api_client.get_performance(performance_id, ANY))


def list_performance_inventories(performance_id) -> list:
    resp = api_client.list_performance_seat_inventories(performance_id, ANY)
    return get_success_data(resp)


def get_seat_inventory(inventory_id) -> dict:
    return get_success_data(api_client.get_seat_inventory(inventory_id, ANY))


def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy scenarios
# ---------------------------------------------------------------------------
def setup_rehearsal_production_with_room(title="Giselle", **production_overrides) -> dict:
    """Production in REHEARSAL plus one rehearsal room."""
    production = create_production_in_state("REHEARSAL", title=title, **production_overrides)
    room = create_rehearsal_room()
    return {"production": production, "room": room}


def setup_on_sale_performance(sections=None, starts_at="2026-07-01T19:00:00Z",
                              ends_at="2026-07-01T22:00:00Z", production=None,
                              **production_overrides) -> dict:
    """Production in REHEARSAL + one performance with sales opened.

    Returns {"production", "performance", "inventories"}.
    """
    if production is None:
        production = create_production_in_state(
            "REHEARSAL", title="Carmen", work_type="OPERA", **production_overrides
        )
    performance = create_performance(production["id"], starts_at, ends_at, sections)
    open_performance_sales(performance["id"])
    inventories = list_performance_inventories(performance["id"])
    return {
        "production": production,
        "performance": performance,
        "inventories": inventories,
    }


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_confirmed_principal(production=None, role_name="Odette/Odile",
                              voice_type="DANCER_F", officer_user_id="officer-1") -> dict:
    """Production in BUILD + role + ACTIVE contract + CONFIRMED PRINCIPAL."""
    if production is None:
        production = create_production_in_state("BUILD")
    role = create_role(production["id"], role_name=role_name, voice_type=voice_type)
    artist, contract = create_active_contract(production["id"], officer_user_id=officer_user_id)
    assignment = create_cast_assignment(role["id"], contract["id"], slot="PRINCIPAL")
    assignment = confirm_cast_assignment(assignment["id"])
    return {
        "production": production,
        "role": role,
        "artist": artist,
        "contract": contract,
        "principal": assignment,
    }


def setup_fully_cast_role(with_second_cover=False) -> dict:
    """CONFIRMED principal + CONFIRMED COVER_1 (+ optional CONFIRMED COVER_2)."""
    base = setup_confirmed_principal()
    production, role, principal = base["production"], base["role"], base["principal"]

    artist_b, contract_b = create_active_contract(
        production["id"],
        artist_overrides={"full_name": "Bella Cover"},
        engagement_type="COVER",
        hourly_rate_cents=6_000,
        weekly_hours_cap=25,
    )
    cover1 = create_cast_assignment(
        role["id"], contract_b["id"], slot="COVER_1", covers_assignment_id=principal["id"]
    )
    cover1 = confirm_cast_assignment(cover1["id"])
    result = dict(base)
    result.update({"cover1": cover1, "contract_b": contract_b, "artist_b": artist_b})

    if with_second_cover:
        artist_c, contract_c = create_active_contract(
            production["id"],
            artist_overrides={"full_name": "Carla Cover", "discipline": "CORPS_DANCER"},
            engagement_type="COVER",
            hourly_rate_cents=5_500,
            weekly_hours_cap=25,
        )
        cover2 = create_cast_assignment(
            role["id"], contract_c["id"], slot="COVER_2", covers_assignment_id=principal["id"]
        )
        cover2 = confirm_cast_assignment(cover2["id"])
        result.update({"cover2": cover2, "contract_c": contract_c, "artist_c": artist_c})
    return result


def create_completed_call_with_confirmed_participant(production_id, room_id, contract_id,
                                                     starts_at, ends_at,
                                                     call_type="DANCE_CALL",
                                                     officer_user_id="officer-1"):
    """Create call -> PUBLISHED -> participant -> CONFIRMED -> COMPLETED."""
    call = create_published_call(
        production_id, room_id, starts_at, ends_at, call_type=call_type
    )
    participant = create_confirmed_participant(
        call["id"], contract_id, officer_user_id=officer_user_id
    )
    call = transition_rehearsal_call(call["id"], "COMPLETED")
    return call, participant


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------
def setup_week_calls(contract_id, production_id, room_id, specs, officer_user_id="officer-1"):
    """Build the calls of one pay week.

    specs: list of (call_type, starts_at, ends_at, final_state) where
    final_state is "COMPLETED", "PUBLISHED", or "DRAFT". The contract is added
    and CONFIRMED on every call; the call is then moved to its target state.
    """
    calls = []
    for call_type, starts_at, ends_at, final_state in specs:
        call = create_rehearsal_call(
            production_id, room_id, starts_at, ends_at, call_type=call_type
        )
        if final_state in ("PUBLISHED", "COMPLETED"):
            call = transition_rehearsal_call(call["id"], "PUBLISHED")
        participant = create_confirmed_participant(
            call["id"], contract_id, officer_user_id=officer_user_id
        )
        if final_state == "COMPLETED":
            call = transition_rehearsal_call(call["id"], "COMPLETED")
        calls.append({"call": call, "participant": participant})
    return calls


def setup_pay_week_projected_vs_final() -> dict:
    """Week of 2026-06-01: 12h+12h+15h COMPLETED (one night call) and 4h PUBLISHED.

    Contract: 8,000 cents/h, weekly cap 30h, default 12h rest floor; consecutive
    calls are exactly 12h apart so the rest floor passes at the boundary.
    """
    production = create_production_in_state("REHEARSAL", title="Giselle",
                                            build_budget_cents=50_000_000)
    room = create_rehearsal_room()
    artist, contract = create_active_contract(
        production["id"], hourly_rate_cents=8_000, weekly_hours_cap=30
    )
    calls = setup_week_calls(
        contract["id"], production["id"], room["id"],
        [
            ("DANCE_CALL", "2026-06-01T08:00:00Z", "2026-06-01T20:00:00Z", "COMPLETED"),
            ("DANCE_CALL", "2026-06-02T08:00:00Z", "2026-06-02T20:00:00Z", "COMPLETED"),
            ("DRESS", "2026-06-03T08:00:00Z", "2026-06-03T23:00:00Z", "COMPLETED"),
            ("BLOCKING", "2026-06-04T11:00:00Z", "2026-06-04T15:00:00Z", "PUBLISHED"),
        ],
    )
    return {"production": production, "room": room, "artist": artist,
            "contract": contract, "calls": calls}


def setup_overtime_week() -> dict:
    """Week of 2026-06-01: 12h COMPLETED + 11h COMPLETED ending 23:00 (night).

    Contract: 5,000 cents/h, weekly cap 10h; the gap between calls is 16h.
    """
    production = create_production_in_state("REHEARSAL", title="Otello",
                                            work_type="OPERA", build_budget_cents=80_000_000)
    room = create_rehearsal_room(name="Studio 2", capacity=30, hourly_rate_cents=4_000)
    artist, contract = create_active_contract(
        production["id"], hourly_rate_cents=5_000, weekly_hours_cap=10,
        artist_overrides={"full_name": "Otello Tenor", "discipline": "TENOR"},
    )
    calls = setup_week_calls(
        contract["id"], production["id"], room["id"],
        [
            ("STAGING", "2026-06-01T08:00:00Z", "2026-06-01T20:00:00Z", "COMPLETED"),
            ("TECH", "2026-06-02T12:00:00Z", "2026-06-02T23:00:00Z", "COMPLETED"),
        ],
    )
    return {"production": production, "room": room, "artist": artist,
            "contract": contract, "calls": calls}


def setup_mixed_status_week() -> dict:
    """Week of 2026-06-01: 12h COMPLETED + 12h PUBLISHED + 12h DRAFT.

    Contract: 8,000 cents/h, weekly cap 30h; calls exactly 12h apart.
    """
    production = create_production_in_state("REHEARSAL", title="Giselle",
                                            build_budget_cents=50_000_000)
    room = create_rehearsal_room()
    artist, contract = create_active_contract(
        production["id"], hourly_rate_cents=8_000, weekly_hours_cap=30
    )
    calls = setup_week_calls(
        contract["id"], production["id"], room["id"],
        [
            ("DANCE_CALL", "2026-06-01T08:00:00Z", "2026-06-01T20:00:00Z", "COMPLETED"),
            ("BLOCKING", "2026-06-02T08:00:00Z", "2026-06-02T20:00:00Z", "PUBLISHED"),
            ("STAGING", "2026-06-03T08:00:00Z", "2026-06-03T20:00:00Z", "DRAFT"),
        ],
    )
    return {"production": production, "room": room, "artist": artist,
            "contract": contract, "calls": calls}


def setup_night_boundary_week() -> dict:
    """Week of 2026-06-01: 12h COMPLETED (ends 20:00) + 15h COMPLETED (ends 23:00)."""
    production = create_production_in_state("REHEARSAL", title="Giselle",
                                            build_budget_cents=50_000_000)
    room = create_rehearsal_room()
    artist, contract = create_active_contract(
        production["id"], hourly_rate_cents=8_000, weekly_hours_cap=30
    )
    calls = setup_week_calls(
        contract["id"], production["id"], room["id"],
        [
            ("DANCE_CALL", "2026-06-01T08:00:00Z", "2026-06-01T20:00:00Z", "COMPLETED"),
            ("DRESS", "2026-06-02T08:00:00Z", "2026-06-02T23:00:00Z", "COMPLETED"),
        ],
    )
    return {"production": production, "room": room, "artist": artist,
            "contract": contract, "calls": calls}


def setup_contract_with_confirmed_call(call_starts_at="2026-06-01T08:00:00Z",
                                       call_ends_at="2026-06-01T20:00:00Z",
                                       rest_floor_hours=12,
                                       hourly_rate_cents=8_000,
                                       weekly_hours_cap=30,
                                       officer_user_id="officer-1") -> dict:
    """Production in REHEARSAL; ACTIVE contract CONFIRMED on one PUBLISHED call."""
    production = create_production_in_state("REHEARSAL", title="Giselle",
                                            build_budget_cents=50_000_000)
    room = create_rehearsal_room()
    artist, contract = create_active_contract(
        production["id"], officer_user_id=officer_user_id,
        hourly_rate_cents=hourly_rate_cents, weekly_hours_cap=weekly_hours_cap,
        rest_floor_hours=rest_floor_hours,
    )
    call_a = create_published_call(
        production["id"], room["id"], call_starts_at, call_ends_at
    )
    participant_a = create_confirmed_participant(
        call_a["id"], contract["id"], officer_user_id=officer_user_id
    )
    return {"production": production, "room": room, "artist": artist,
            "contract": contract, "call_a": call_a, "participant_a": participant_a}


# ---------------------------------------------------------------------------
# Tier 5: performance readiness / settlement scenarios
# ---------------------------------------------------------------------------
def setup_readiness_scenario(surtitle_final_state="LIVE", with_done_tech_slot=True) -> dict:
    """Production in REHEARSAL + surtitle track walked to the requested state
    + (optionally) a DONE tech slot ending before curtain + one performance."""
    production = create_production_in_state("REHEARSAL", title="Carmen", work_type="OPERA",
                                            build_budget_cents=60_000_000)
    track = create_surtitle_track(production["id"], language="en", cue_count=400)
    if surtitle_final_state in ("TRANSLATED", "CUES_LOCKED", "LIVE"):
        track = transition_surtitle_track(track["id"], "TRANSLATED")
    if surtitle_final_state in ("CUES_LOCKED", "LIVE"):
        track = transition_surtitle_track(track["id"], "CUES_LOCKED")
    if surtitle_final_state == "LIVE":
        track = transition_surtitle_track(track["id"], "LIVE")
    slot = None
    if with_done_tech_slot:
        slot = create_done_tech_slot(
            production["id"], "2026-07-04T10:00:00Z", "2026-07-04T14:00:00Z"
        )
    performance = create_performance(
        production["id"], "2026-07-05T19:00:00Z", "2026-07-05T22:00:00Z",
        sections=[{"section": "STALLS", "total_seats": 50, "base_price_cents": 15_000}],
    )
    return {"production": production, "track": track, "slot": slot,
            "performance": performance}


def setup_cleared_performance() -> dict:
    """Readiness scenario fully cleared: TECH_READY then CLEARED_FOR_AUDIENCE."""
    scenario = setup_readiness_scenario(surtitle_final_state="LIVE", with_done_tech_slot=True)
    perf_id = scenario["performance"]["id"]
    get_success_data(api_client.mark_tech_ready(perf_id, TD))
    scenario["performance"] = get_success_data(api_client.clear_for_audience(perf_id, TD))
    return scenario


def setup_net_share_performance(share_percentage=40) -> dict:
    """Production in REHEARSAL with a RATIFIED NET_REVENUE_SHARE co-production
    share and one ON_SALE performance (STALLS 100 @ 20,000)."""
    company = create_partner_company(name="NetCo", partner_kind="CO_PRODUCER")
    production = create_production(title="Swan Lake", build_budget_cents=100_000_000)
    share = create_share(production["id"], company["id"], share_percentage, "NET_REVENUE_SHARE")
    share = transition_share(share["id"], "RATIFIED")
    production = transition_production(production["id"], "BUILD")
    production = transition_production(production["id"], "REHEARSAL")
    performance = create_performance(
        production["id"], "2026-06-20T19:00:00Z", "2026-06-20T22:00:00Z",
        sections=[{"section": "STALLS", "total_seats": 100, "base_price_cents": 20_000}],
    )
    open_performance_sales(performance["id"])
    inventory = list_performance_inventories(performance["id"])[0]
    return {"company": company, "production": production, "share": share,
            "performance": performance, "inventory": inventory}


def setup_copro_settlement_scenario() -> dict:
    """Two DELIVERED build items (actuals 20,000,000 and 5,000,000), two RATIFIED
    40% shares (GrossCo GROSS_COST, NetCo NET_REVENUE_SHARE), and one ON_SALE
    performance with 5 seats sold (season revenue 100,000)."""
    gross_co = create_partner_company(name="GrossCo", partner_kind="CO_PRODUCER")
    net_co = create_partner_company(name="NetCo", partner_kind="CO_PRODUCER")
    production = create_production(title="Swan Lake", build_budget_cents=100_000_000)

    item1 = create_build_item(production["id"], item_kind="SET", name="Palace flat",
                              quoted_cost_cents=18_000_000)
    item1 = transition_build_item(item1["id"], "BUILT", actual_cost_cents=20_000_000)
    item1 = transition_build_item(item1["id"], "DELIVERED")
    item2 = create_build_item(production["id"], item_kind="COSTUME", name="Tutus",
                              quoted_cost_cents=5_000_000)
    item2 = transition_build_item(item2["id"], "BUILT", actual_cost_cents=5_000_000)
    item2 = transition_build_item(item2["id"], "DELIVERED")

    share_g = create_share(production["id"], gross_co["id"], 40, "GROSS_COST")
    share_n = create_share(production["id"], net_co["id"], 40, "NET_REVENUE_SHARE")
    share_g = transition_share(share_g["id"], "RATIFIED")
    share_n = transition_share(share_n["id"], "RATIFIED")

    production = transition_production(production["id"], "BUILD")
    production = transition_production(production["id"], "REHEARSAL")
    performance = create_performance(
        production["id"], "2026-06-20T19:00:00Z", "2026-06-20T22:00:00Z",
        sections=[{"section": "STALLS", "total_seats": 100, "base_price_cents": 20_000}],
    )
    open_performance_sales(performance["id"])
    inventory = list_performance_inventories(performance["id"])[0]
    get_success_data(api_client.purchase_seats(inventory["id"], 5, BOM))
    return {"gross_co": gross_co, "net_co": net_co, "production": production,
            "items": [item1, item2], "share_g": share_g, "share_n": share_n,
            "performance": performance, "inventory": inventory}


# ---------------------------------------------------------------------------
# Rental offers
# ---------------------------------------------------------------------------
def create_rental_offer(production_id, renter_company_id, manager_user_id="pm-1",
                        **overrides) -> dict:
    """Create an offer, threading the production's current version (PRD §2.7)."""
    production = get_production(production_id)
    payload = create_rental_offer_payload(
        production_id, renter_company_id,
        expected_production_version=production["version"], **overrides,
    )
    headers = make_production_manager_headers(manager_user_id)
    return get_success_data(api_client.create_rental_offer(payload, headers))


def send_rental_offer(offer_id, manager_user_id="pm-1") -> dict:
    headers = make_production_manager_headers(manager_user_id)
    return get_success_data(api_client.send_rental_offer(offer_id, headers))


def revise_rental_offer(offer_id, per_performance_fee_cents, manager_user_id="pm-1") -> dict:
    headers = make_production_manager_headers(manager_user_id)
    return get_success_data(
        api_client.revise_rental_offer(offer_id, per_performance_fee_cents, headers)
    )


def counter_rental_offer(offer_id, renter_company_id, countered_fee_cents) -> dict:
    headers = make_partner_representative_headers(renter_company_id)
    return get_success_data(
        api_client.counter_rental_offer(offer_id, countered_fee_cents, headers)
    )


def accept_rental_offer(offer_id, renter_company_id) -> dict:
    headers = make_partner_representative_headers(renter_company_id)
    return get_success_data(api_client.accept_rental_offer(offer_id, headers))


def decline_rental_offer(offer_id, renter_company_id) -> dict:
    headers = make_partner_representative_headers(renter_company_id)
    return get_success_data(api_client.decline_rental_offer(offer_id, headers))


def get_rental_offer(offer_id) -> dict:
    return get_success_data(api_client.get_rental_offer(offer_id, ANY))


def setup_sent_offer(performances_count=7, per_performance_fee_cents=700_000,
                     manager_user_id="pm-1", renter_name="TourCo") -> dict:
    """RENTER company (standing GOOD) + production + one SENT rental offer."""
    renter = create_partner_company(name=renter_name, partner_kind="RENTER")
    production = create_production(title="Nutcracker", build_budget_cents=40_000_000)
    offer = create_rental_offer(
        production["id"], renter["id"], manager_user_id=manager_user_id,
        performances_count=performances_count,
        per_performance_fee_cents=per_performance_fee_cents,
    )
    offer = send_rental_offer(offer["id"], manager_user_id=manager_user_id)
    return {"renter": renter, "production": production, "offer": offer}
