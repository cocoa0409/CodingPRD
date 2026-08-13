"""Composite setup helpers.

Encapsulates the multi-step API sequences that PRD workflows require so tests
can focus on assertions. All setup calls use get_success_data() so a setup
failure raises a clear "Setup step failed" error.

The logical clock starts at 2026-08-01T00:00:00Z on every fresh server
(PRD §2.5); fixtures that need a different clock set it explicitly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_birth_record_payload,
    create_breeding_season_payload,
    create_consignment_payload,
    create_core_test_payload,
    create_core_test_results_payload,
    create_flock_payload,
    create_grazing_contract_payload,
    create_grazing_move_payload,
    create_holiday_window_payload,
    create_livestock_sale_payload,
    create_loss_report_payload,
    create_parasite_treatment_payload,
    create_pasture_payload,
    create_shearing_crew_payload,
    create_shearing_event_payload,
    create_wool_lot_payload,
)
from .test_users import TEST_USERS, make_ranch_manager_headers, make_wool_pool_operator_headers

RM = TEST_USERS["ranch_manager_headers"]
RH = TEST_USERS["range_hand_headers"]
WPO = TEST_USERS["wool_pool_operator_headers"]
GC = TEST_USERS["grazing_client_headers"]
PA = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: base entities
# ---------------------------------------------------------------------------

def create_flock(**overrides):
    """Create a flock; returns the Flock body."""
    return get_success_data(api_client.create_flock(create_flock_payload(**overrides), RM))


def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, PA))


def create_pasture(**overrides):
    return get_success_data(api_client.create_pasture(create_pasture_payload(**overrides), RM))


def create_crew(**overrides):
    return get_success_data(api_client.create_shearing_crew(create_shearing_crew_payload(**overrides), RM))


def create_holiday_window(**overrides):
    return get_success_data(api_client.create_holiday_window(create_holiday_window_payload(**overrides), RM))


# ---------------------------------------------------------------------------
# Tier 1: breeding season chain
# ---------------------------------------------------------------------------

def create_season(flock_id, **overrides):
    payload = create_breeding_season_payload(flock_id=flock_id, **overrides)
    return get_success_data(api_client.create_breeding_season(payload, RM))


def transition_season(season_id, to, headers=None):
    return get_success_data(
        api_client.transition_breeding_season(season_id, {"to": to}, headers or RM)
    )


def create_season_in_state(flock_id, target_state, **overrides):
    """Walk a season to a target state, driving the logical clock through the
    PRD §3.1 gates (defaults assume a SHEEP flock: +147 day gestation).

    Clock path: BREEDING (immediate) -> clock to breeding_end -> GESTATION ->
    clock to expected_lambing_start -> LAMBING -> clock +45d -> WEANING ->
    CLOSED.
    """
    season = create_season(flock_id, **overrides)
    sid = season["id"]
    if target_state == "PLANNED":
        return season
    season = transition_season(sid, "BREEDING")
    if target_state == "BREEDING":
        return season
    set_clock(season["breeding_end_date"])
    season = transition_season(sid, "GESTATION")
    if target_state == "GESTATION":
        return season
    set_clock(season["expected_lambing_start"])
    season = transition_season(sid, "LAMBING")
    if target_state in ("LAMBING",):
        return season
    # expected_lambing_start + 45 days gate for WEANING (PRD §3.1)
    from datetime import datetime, timedelta, timezone

    els = datetime.fromisoformat(season["expected_lambing_start"].replace("Z", "+00:00"))
    weaning_at = (els + timedelta(days=45)).astimezone(timezone.utc)
    set_clock(weaning_at.strftime("%Y-%m-%dT%H:%M:%SZ"))
    season = transition_season(sid, "WEANING")
    if target_state == "WEANING":
        return season
    season = transition_season(sid, "CLOSED")
    return season


def log_birth(season_id, headers=None, **overrides):
    payload = create_birth_record_payload(season_id=season_id, **overrides)
    return get_success_data(api_client.create_birth_record(payload, headers or RH))


# ---------------------------------------------------------------------------
# Tier 2: shearing -> clip -> lot chain
# ---------------------------------------------------------------------------

def create_completed_clip(flock_id, greasy_weight_lbs=200.0, skirtings_weight_lbs=20.0,
                          shorn_head_count=400, crew_capacity=300, crew_daily_rate=40000,
                          expected_head=400, crew_name=None,
                          scheduled_start="2026-08-03T00:00:00Z",
                          scheduled_end="2026-08-05T00:00:00Z",
                          set_clock_to_start=True):
    """Flock must already exist. Books a crew + event, starts it, completes it
    with tallies, and returns (clip, event, crew).

    PRD §3.3: completion cascade-creates exactly one wool clip keyed by
    shearing_event_id, discoverable via the filtered clip list.
    """
    crew_payload = create_shearing_crew_payload(
        head_per_day_capacity=crew_capacity, daily_rate_cents=crew_daily_rate,
    )
    if crew_name:
        crew_payload["crew_name"] = crew_name
    crew = get_success_data(api_client.create_shearing_crew(crew_payload, RM))
    if set_clock_to_start:
        set_clock(scheduled_start)
    event = get_success_data(api_client.create_shearing_event(
        create_shearing_event_payload(
            flock_id=flock_id, crew_id=crew["id"],
            scheduled_start=scheduled_start, scheduled_end=scheduled_end,
            expected_head=expected_head,
        ), RM))
    get_success_data(api_client.transition_shearing_event(event["id"], {"to": "IN_PROGRESS"}, RH))
    event = get_success_data(api_client.complete_shearing_event(event["id"], {
        "shorn_head_count": shorn_head_count,
        "greasy_weight_lbs": greasy_weight_lbs,
        "skirtings_weight_lbs": skirtings_weight_lbs,
    }, RH))
    clips = get_success_data(api_client.list_wool_clips(RM, params={"shearing_event_id": event["id"]}))
    assert isinstance(clips, list) and len(clips) == 1, (
        "Setup failed: expected exactly one clip for the completed shearing event"
    )
    return clips[0], event, crew


def setup_clip_with_lot(greasy_weight_lbs=200.0, skirtings_weight_lbs=20.0,
                        lot_weight_lbs=100.0, lot_code="L1",
                        flock_name=None, baseline_headcount=500, species="SHEEP",
                        crew_name=None):
    """Flock + completed clip + one DRAFT lot. Returns (flock, clip, lot)."""
    flock_kwargs = {"baseline_headcount": baseline_headcount, "species": species}
    if flock_name:
        flock_kwargs["flock_name"] = flock_name
    flock = create_flock(**flock_kwargs)
    clip, _event, _crew = create_completed_clip(
        flock["id"], greasy_weight_lbs=greasy_weight_lbs,
        skirtings_weight_lbs=skirtings_weight_lbs,
        shorn_head_count=baseline_headcount if baseline_headcount < 400 else 400,
        expected_head=baseline_headcount if baseline_headcount < 400 else 400,
        crew_capacity=1000, crew_name=crew_name,
    )
    lot = get_success_data(api_client.create_wool_lot(
        create_wool_lot_payload(clip_id=clip["id"], lot_code=lot_code, weight_lbs=lot_weight_lbs),
        RM))
    return flock, clip, lot


def grade_lot(lot_id, estimated_micron=20.0, headers=None):
    return get_success_data(
        api_client.grade_wool_lot(lot_id, {"estimated_micron": estimated_micron}, headers or RM))


def setup_graded_lot(estimated_micron=20.0, **kwargs):
    """Flock + clip + GRADED lot. Returns (flock, clip, lot)."""
    flock, clip, lot = setup_clip_with_lot(**kwargs)
    lot = grade_lot(lot["id"], estimated_micron)
    return flock, clip, lot


# ---------------------------------------------------------------------------
# Tier 3: consignment pipeline
# ---------------------------------------------------------------------------

def consign_lot(lot_id, pool_ref="WWPA-POOL"):
    return get_success_data(
        api_client.create_consignment(create_consignment_payload(lot_id=lot_id, pool_ref=pool_ref), RM))


def transition_consignment(consignment_id, to, headers=None):
    return get_success_data(
        api_client.transition_consignment(consignment_id, {"to": to}, headers or WPO))


def setup_consigned_lot(estimated_micron=20.0, pool_ref="WWPA-POOL", **kwargs):
    """Flock + clip + GRADED lot + TENDERED consignment (lot now CONSIGNED)."""
    flock, clip, lot = setup_graded_lot(estimated_micron=estimated_micron, **kwargs)
    con = consign_lot(lot["id"], pool_ref)
    return flock, clip, lot, con


def setup_advanced_consignment(estimated_micron=20.0, pool_ref="WWPA-POOL", **kwargs):
    """Consignment walked to ADVANCED (advance posted at 70% of effective value)."""
    flock, clip, lot, con = setup_consigned_lot(estimated_micron=estimated_micron, pool_ref=pool_ref, **kwargs)
    con = transition_consignment(con["id"], "ACCEPTED")
    con = transition_consignment(con["id"], "ADVANCED")
    return flock, clip, lot, con


def setup_settled_consignment(estimated_micron=20.0, pool_ref="WWPA-POOL",
                              sale_gross_cents=100000, **kwargs):
    """Consignment walked all the way to SETTLED."""
    flock, clip, lot, con = setup_advanced_consignment(
        estimated_micron=estimated_micron, pool_ref=pool_ref, **kwargs)
    con = get_success_data(api_client.sell_consignment(con["id"], {"sale_gross_cents": sale_gross_cents}, WPO))
    con = transition_consignment(con["id"], "SETTLED")
    return flock, clip, lot, con


# ---------------------------------------------------------------------------
# Tier 3: core tests
# ---------------------------------------------------------------------------

def submit_core_test(lot_id, lab_ref="LAB-1", user_id="wpo-1"):
    """Submit a core test as the pool operator; submitted_by_user_id := user_id."""
    return get_success_data(api_client.create_core_test(
        create_core_test_payload(lot_id=lot_id, lab_ref=lab_ref),
        make_wool_pool_operator_headers(user_id)))


def post_results(test_id, measured_micron=19.0, clean_yield_pct=62.0,
                 vegetable_matter_pct=1.2, user_id="wpo-1"):
    return get_success_data(api_client.post_core_test_results(
        test_id,
        create_core_test_results_payload(
            measured_micron=measured_micron, clean_yield_pct=clean_yield_pct,
            vegetable_matter_pct=vegetable_matter_pct),
        make_wool_pool_operator_headers(user_id)))


def lock_core_test(test_id, user_id="rm-1"):
    return get_success_data(api_client.transition_core_test(
        test_id, {"to": "LOCKED"}, make_ranch_manager_headers(user_id)))


def setup_resulted_core_test(lot_id, measured_micron=19.0, clean_yield_pct=62.0,
                             vegetable_matter_pct=1.2, lab_ref="LAB-1",
                             submitter_id="wpo-1"):
    """CoreTest walked SUBMITTED -> RESULTED. Returns the test."""
    test = submit_core_test(lot_id, lab_ref=lab_ref, user_id=submitter_id)
    return post_results(test["id"], measured_micron, clean_yield_pct,
                        vegetable_matter_pct, user_id=submitter_id)


# ---------------------------------------------------------------------------
# Tier 2: grazing contracts and moves
# ---------------------------------------------------------------------------

def create_contract(flock_id, **overrides):
    payload = create_grazing_contract_payload(flock_id=flock_id, **overrides)
    return get_success_data(api_client.create_grazing_contract(payload, RM))


def transition_contract(contract_id, to, headers=None):
    return get_success_data(
        api_client.transition_grazing_contract(contract_id, {"to": to}, headers or RM))


def setup_active_contract(flock_id, window_start="2026-09-01T00:00:00Z",
                          window_end="2026-09-30T00:00:00Z", clock_in_window="2026-09-02T00:00:00Z",
                          **overrides):
    """Contract walked DRAFT -> PROPOSED -> ACCEPTED -> ACTIVE with the logical
    clock inside the service window. Returns the ACTIVE contract."""
    contract = create_contract(
        flock_id, service_window_start=window_start, service_window_end=window_end, **overrides)
    contract = transition_contract(contract["id"], "PROPOSED")
    contract = transition_contract(contract["id"], "ACCEPTED", headers=GC)
    set_clock(clock_in_window)
    contract = transition_contract(contract["id"], "ACTIVE")
    return contract


def create_move(flock_id, pasture_id=None, contract_id=None, headers=None, **overrides):
    payload = create_grazing_move_payload(flock_id=flock_id, **overrides)
    if pasture_id is not None:
        payload["pasture_id"] = pasture_id
    if contract_id is not None:
        payload["contract_id"] = contract_id
    return get_success_data(api_client.create_grazing_move(payload, headers or RH))


def transition_move(move_id, to, headers=None):
    return get_success_data(
        api_client.transition_grazing_move(move_id, {"to": to}, headers or RH))


# ---------------------------------------------------------------------------
# Tier 2: parasite treatments
# ---------------------------------------------------------------------------

def create_treatment(flock_id, headers=None, **overrides):
    payload = create_parasite_treatment_payload(flock_id=flock_id, **overrides)
    return get_success_data(api_client.create_parasite_treatment(payload, headers or RH))


# ---------------------------------------------------------------------------
# Tier 3: livestock sales
# ---------------------------------------------------------------------------

def create_sale(flock_id, **overrides):
    payload = create_livestock_sale_payload(flock_id=flock_id, **overrides)
    return get_success_data(api_client.create_livestock_sale(payload, RM))


def pay_sale(sale_id, amount_cents):
    return get_success_data(
        api_client.record_sale_payment(sale_id, {"amount_cents": amount_cents}, RM))


def setup_paid_sale(flock_id, **overrides):
    """Sale created and paid at its booked price. Returns the sale."""
    sale = create_sale(flock_id, **overrides)
    return pay_sale(sale["id"], sale["booked_price_cents"])


def setup_loaded_sale(flock_id, **overrides):
    sale = setup_paid_sale(flock_id, **overrides)
    return get_success_data(api_client.load_sale(sale["id"], RH))


# ---------------------------------------------------------------------------
# Tier 3: loss reports
# ---------------------------------------------------------------------------

def create_loss_report(flock_id, headers=None, **overrides):
    payload = create_loss_report_payload(flock_id=flock_id, **overrides)
    return get_success_data(api_client.create_loss_report(payload, headers or RH))


def transition_loss_report(report_id, to, headers=None):
    return get_success_data(
        api_client.transition_loss_report(report_id, {"to": to}, headers or RM))


def setup_under_review_loss(flock_id, **overrides):
    report = create_loss_report(flock_id, **overrides)
    return transition_loss_report(report["id"], "UNDER_REVIEW")
