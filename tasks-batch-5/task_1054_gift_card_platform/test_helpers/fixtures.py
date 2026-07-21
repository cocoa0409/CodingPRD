"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally, so a broken setup step
surfaces as a clear "Setup failed" rather than a confusing assertion later.

The test harness restarts the API server (empty DB, logical clock reset to
2026-07-01T00:00:00Z) before every individual test, so every helper builds its
preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_merchant_payload, create_card_program_payload,
    create_incentive_campaign_payload, create_card_batch_payload,
    create_velocity_rule_payload, create_settlement_batch_payload,
    create_escheat_report_payload, redeem_payload, reload_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS, make_merchant_admin_headers, make_fraud_analyst_headers,
    make_settlement_officer_headers,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
POS = TEST_USERS["pos_terminal_headers"]
ANY = TEST_USERS["any_headers"]

DEFAULT_PERIOD_START = "2026-07-01T00:00:00Z"
DEFAULT_PERIOD_END = "2026-08-01T00:00:00Z"


# ─────────────────────── Primitive steps ───────────────────────

def set_clock(to_iso8601: str):
    """Set the server logical clock (PlatformAdmin only)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), PLATFORM))


def create_active_merchant(legal_name: str = "Acme Retail") -> dict:
    """POST /merchants + activate -> ACTIVE merchant."""
    merchant = get_success_data(
        api_client.create_merchant(create_merchant_payload(legal_name=legal_name), PLATFORM))
    return get_success_data(api_client.activate_merchant(merchant["id"], PLATFORM))


def create_draft_program(merchant_id: str, **overrides) -> dict:
    """POST /card-programs -> DRAFT program (owned by merchant_id)."""
    admin = make_merchant_admin_headers(merchant_id)
    return get_success_data(api_client.create_card_program(
        create_card_program_payload(merchant_id, **overrides), admin))


def create_active_program(merchant_id: str, **overrides) -> dict:
    """POST /card-programs + activate -> ACTIVE program."""
    admin = make_merchant_admin_headers(merchant_id)
    program = create_draft_program(merchant_id, **overrides)
    return get_success_data(api_client.activate_card_program(program["id"], admin))


def commit_batch(merchant_id: str, program_id: str, card_count: int,
                 unit_load_cents: int, channel: str = "DIGITAL", **overrides) -> dict:
    """POST /card-batches + commit -> COMMITTED batch (mints cards)."""
    admin = make_merchant_admin_headers(merchant_id)
    batch = get_success_data(api_client.create_card_batch(
        create_card_batch_payload(program_id, card_count, unit_load_cents,
                                  channel=channel, **overrides), admin))
    return get_success_data(api_client.commit_card_batch(batch["id"], admin))


def get_batch_cards(batch_id: str) -> list:
    """List the gift cards minted by a batch (ordered by created_at ascending)."""
    res = api_client.list_gift_cards(ANY, params={"card_batch_id": batch_id})
    return get_success_data(res)


def activate_card(card_id: str) -> dict:
    """POST /gift-cards/{id}/activate -> ACTIVE card."""
    return get_success_data(api_client.activate_gift_card(card_id, POS))


def redeem(card_id: str, amount_cents: int) -> dict:
    """POST /gift-cards/{id}/redeem."""
    return get_success_data(
        api_client.redeem_gift_card(card_id, redeem_payload(amount_cents), POS))


def do_reload(card_id: str, amount_cents: int) -> dict:
    """POST /gift-cards/{id}/reload."""
    return get_success_data(
        api_client.reload_gift_card(card_id, reload_payload(amount_cents), POS))


def merchant_version(merchant_id: str) -> int:
    """Read the merchant's current version (for the settlement OCC field)."""
    return get_success_data(api_client.get_merchant(merchant_id, ANY))["version"]


def open_settlement(merchant_id: str, period_start: str = DEFAULT_PERIOD_START,
                    period_end: str = DEFAULT_PERIOD_END,
                    officer_id: str = "officer-1", expected_version: int = None) -> dict:
    """POST /settlement-batches with a fresh expected_merchant_version."""
    version = merchant_version(merchant_id) if expected_version is None else expected_version
    officer = make_settlement_officer_headers(officer_id)
    return get_success_data(api_client.open_settlement_batch(
        create_settlement_batch_payload(merchant_id, period_start, period_end, version),
        officer))


def open_hold(card_id: str, reason: str = "MANUAL", analyst_id: str = "analyst-1") -> dict:
    """POST /fraud-holds -> OPEN hold; freezes card ACTIVE->SUSPENDED."""
    analyst = make_fraud_analyst_headers(analyst_id)
    return get_success_data(api_client.open_fraud_hold(
        {"gift_card_id": card_id, "reason": reason}, analyst))


def create_campaign(merchant_id: str, program_id: str, starts_at: str, ends_at: str,
                    bonus_bps: int = 1000, name: str = "Campaign") -> dict:
    """POST /incentive-campaigns."""
    admin = make_merchant_admin_headers(merchant_id)
    return get_success_data(api_client.create_incentive_campaign(
        create_incentive_campaign_payload(program_id, starts_at, ends_at,
                                           bonus_bps=bonus_bps, name=name), admin))


def create_velocity_rule(merchant_id: str, program_id: str, **overrides) -> dict:
    """POST /velocity-rules."""
    admin = make_merchant_admin_headers(merchant_id)
    return get_success_data(api_client.create_velocity_rule(
        create_velocity_rule_payload(program_id, **overrides), admin))


# ─────────────────────── Composite setups ───────────────────────

def setup_single_active_card(unit_load_cents: int = 100_000, program_overrides=None,
                             activate: bool = True, channel: str = "DIGITAL"):
    """Active merchant + active program + committed 1-card batch.

    Returns (merchant, program, batch, card). The card is ACTIVE (activated with
    its initial load) when activate=True, else INACTIVE.
    """
    merchant = create_active_merchant()
    program = create_active_program(merchant["id"], **(program_overrides or {}))
    batch = commit_batch(merchant["id"], program["id"], 1, unit_load_cents, channel=channel)
    card = get_batch_cards(batch["id"])[0]
    if activate:
        card = activate_card(card["id"])
    return merchant, program, batch, card


def setup_multi_active_cards(card_count: int, unit_load_cents: int,
                             program_overrides=None, activate: bool = True):
    """Active merchant + active program + committed N-card batch.

    Returns (merchant, program, batch, cards). Every card is ACTIVE when
    activate=True (in list order, which is created_at ascending).
    """
    merchant = create_active_merchant()
    program = create_active_program(merchant["id"], **(program_overrides or {}))
    batch = commit_batch(merchant["id"], program["id"], card_count, unit_load_cents)
    cards = get_batch_cards(batch["id"])
    if activate:
        cards = [activate_card(c["id"]) for c in cards]
    return merchant, program, batch, cards


def setup_inactive_card_with_program_state(target_state: str, unit_load_cents: int = 5_000):
    """Committed batch (1 INACTIVE card) whose program is driven to target_state
    (one of PAUSED, RETIRED). Returns (merchant, program, card_inactive).

    Used by the cross-entity guard tests where card activation must be rejected
    because the owning program is not ACTIVE.
    """
    merchant = create_active_merchant()
    program = create_active_program(merchant["id"])
    admin = make_merchant_admin_headers(merchant["id"])
    batch = commit_batch(merchant["id"], program["id"], 1, unit_load_cents)
    card = get_batch_cards(batch["id"])[0]
    if target_state == "PAUSED":
        get_success_data(api_client.pause_card_program(program["id"], admin))
    elif target_state == "RETIRED":
        get_success_data(api_client.retire_card_program(program["id"], admin))
    else:
        raise ValueError(f"unsupported target_state {target_state}")
    return merchant, program, card


def setup_active_card_with_open_hold(unit_load_cents: int = 100_000, reason: str = "MANUAL",
                                     redeem_amount: int = None, analyst_id: str = "analyst-1"):
    """Active card (optionally redeemed first), then a fraud hold opened on it so
    the card is SUSPENDED. Returns (merchant, program, card_after_hold, hold).
    """
    merchant, program, _batch, card = setup_single_active_card(unit_load_cents)
    if redeem_amount:
        card = redeem(card["id"], redeem_amount)
    hold = open_hold(card["id"], reason=reason, analyst_id=analyst_id)
    card = get_success_data(api_client.get_gift_card(card["id"], ANY))
    return merchant, program, card, hold


def setup_active_card_retired_program(unit_load_cents: int = 90_000):
    """Active card whose owning program is then RETIRED (card stays ACTIVE).
    Returns (merchant, program, card). Used for reload-referential tests.
    """
    merchant, program, _batch, card = setup_single_active_card(unit_load_cents)
    admin = make_merchant_admin_headers(merchant["id"])
    program = get_success_data(api_client.retire_card_program(program["id"], admin))
    return merchant, program, card


def setup_velocity_scenario(prior_redemptions: int, redemption_amount: int = 1_000,
                            unit_load_cents: int = 10_000, max_count: int = 5,
                            max_amount_cents: int = 50_000, window_hours: int = 24):
    """Active card under a VelocityRule, with `prior_redemptions` in-window
    redemptions already POSTED. Returns (merchant, program, card, rule).
    """
    merchant = create_active_merchant()
    program = create_active_program(merchant["id"])
    rule = create_velocity_rule(merchant["id"], program["id"], window_hours=window_hours,
                                max_count=max_count, max_amount_cents=max_amount_cents,
                                enabled=True)
    batch = commit_batch(merchant["id"], program["id"], 1, unit_load_cents)
    card = activate_card(get_batch_cards(batch["id"])[0]["id"])
    for _ in range(prior_redemptions):
        card = redeem(card["id"], redemption_amount)
    return merchant, program, card, rule


def setup_expired_card_pending_maintenance(breakage_method: str = "REMITTANCE",
                                           unit_load_cents: int = 30_000,
                                           expiry_months: int = 12,
                                           clock_after: str = "2027-07-02T00:00:00Z"):
    """Active card whose program expires it once the clock is advanced past
    expires_at; run-maintenance is NOT yet called. Returns (merchant, program, card).
    """
    merchant, program, _batch, card = setup_single_active_card(
        unit_load_cents,
        program_overrides={"breakage_method": breakage_method, "expiry_months": expiry_months})
    set_clock(clock_after)
    return merchant, program, card


def setup_card_redeemed_open_settlement(unit_load_cents: int = 100_000,
                                        redeem_amount: int = 20_000):
    """One active card, redeemed once, with a settlement batch OPEN (sweeping the
    redemption) opened by officer-1. Returns (merchant, program, card, settlement).
    """
    merchant, program, _batch, card = setup_single_active_card(unit_load_cents)
    card = redeem(card["id"], redeem_amount)
    settlement = open_settlement(merchant["id"], officer_id="officer-1")
    return merchant, program, card, settlement


def setup_settlement_cascade_pending_confirm(unit_load_cents: int = 100_000,
                                             redeem_amount: int = 20_000):
    """One active card redeemed once, settlement OPEN (swept the redemption), and
    a fraud hold OPEN on the card (not yet confirmed). Returns
    (merchant, program, card, settlement, hold).
    """
    merchant, program, card, settlement = setup_card_redeemed_open_settlement(
        unit_load_cents, redeem_amount)
    hold = open_hold(card["id"], reason="CHARGEBACK", analyst_id="analyst-1")
    card = get_success_data(api_client.get_gift_card(card["id"], ANY))
    return merchant, program, card, settlement, hold


def setup_provisional_vs_final(analyst_open: str = "analyst-1",
                               analyst_confirm: str = "analyst-2"):
    """Two active cards each loaded 100000. Card A redeemed 20000; card B redeemed
    20000 twice (40000). A settlement is opened (gross 60000, provisional net
    57500). A fraud hold on card A is CONFIRMED, reversing A's 20000 so only 40000
    of swept redemptions remain POSTED. The batch is still OPEN.

    Returns dict(merchant, program, card_a, card_b, settlement, hold).
    """
    merchant, program, _batch, cards = setup_multi_active_cards(2, 100_000)
    card_a, card_b = cards[0], cards[1]
    redeem(card_a["id"], 20_000)
    redeem(card_b["id"], 20_000)
    redeem(card_b["id"], 20_000)
    settlement = open_settlement(merchant["id"], officer_id="officer-1")
    hold = open_hold(card_a["id"], reason="CHARGEBACK", analyst_id=analyst_open)
    get_success_data(api_client.confirm_fraud_hold(
        hold["id"], make_fraud_analyst_headers(analyst_confirm)))
    settlement = get_success_data(api_client.get_settlement_batch(settlement["id"], ANY))
    return {"merchant": merchant, "program": program, "card_a": card_a,
            "card_b": card_b, "settlement": settlement, "hold": hold}


def setup_two_fully_redeemed_cards(unit_load_cents: int = 100_000):
    """Two active cards each loaded `unit_load_cents` and fully redeemed (balance
    0, auto-closed). No settlement yet. Returns (merchant, program, cards).
    """
    merchant, program, _batch, cards = setup_multi_active_cards(2, unit_load_cents)
    for c in cards:
        redeem(c["id"], unit_load_cents)
    return merchant, program, cards


def setup_open_settlement_suspended_merchant(unit_load_cents: int = 100_000,
                                             redeem_amount: int = 20_000):
    """Card redeemed, settlement opened by officer-1, then the merchant SUSPENDED.
    Returns (merchant, program, card, settlement). For finalize-guard tests.
    """
    merchant, program, card, settlement = setup_card_redeemed_open_settlement(
        unit_load_cents, redeem_amount)
    merchant = get_success_data(api_client.suspend_merchant(merchant["id"], PLATFORM))
    return merchant, program, card, settlement


def setup_merchant_with_open_settlement_period(period_start: str = DEFAULT_PERIOD_START,
                                               period_end: str = DEFAULT_PERIOD_END):
    """Active merchant with one OPEN settlement batch over [period_start,
    period_end). Returns (merchant, settlement). For period-overlap tests.
    """
    merchant = create_active_merchant()
    settlement = open_settlement(merchant["id"], period_start, period_end, officer_id="officer-1")
    return merchant, settlement


def setup_program_with_one_campaign(camp_start: str, camp_end: str, bonus_bps: int = 1000):
    """Active merchant + DRAFT program carrying one IncentiveCampaign
    [camp_start, camp_end]. Returns (merchant, program, campaign).
    """
    merchant = create_active_merchant()
    program = create_draft_program(merchant["id"])
    campaign = create_campaign(merchant["id"], program["id"], camp_start, camp_end,
                               bonus_bps=bonus_bps, name="First")
    return merchant, program, campaign


def setup_escheatable_expired_card(unit_load_cents: int = 30_000):
    """ESTIMATED program (so expiry does not forfeit balance); one card activated
    at the default clock, clock advanced to 2027-07-05, run-maintenance applied so
    the card is EXPIRED holding its balance. An escheat report [2027-07-01,
    2027-07-03) is created capturing it. Returns (merchant, program, card, report).
    """
    merchant, program, _batch, card = setup_single_active_card(
        unit_load_cents, program_overrides={"breakage_method": "ESTIMATED", "expiry_months": 12})
    set_clock("2027-07-05T00:00:00Z")
    get_success_data(api_client.run_maintenance(program["id"], PLATFORM))
    card = get_success_data(api_client.get_gift_card(card["id"], ANY))
    officer = make_settlement_officer_headers("officer-1")
    report = get_success_data(api_client.create_escheat_report(
        create_escheat_report_payload(merchant["id"], "CA",
                                      "2027-07-01T00:00:00Z", "2027-07-03T00:00:00Z"), officer))
    return merchant, program, card, report


def setup_active_card_with_running_campaign(unit_load_cents: int = 5_000,
                                            bonus_bps: int = 1000):
    """Active card whose program has a campaign RUNNING at the default clock
    (2026-07-01): window [2026-06-01, 2026-08-01]. Returns (merchant, program,
    campaign, card).
    """
    merchant = create_active_merchant()
    program = create_active_program(merchant["id"])
    campaign = create_campaign(merchant["id"], program["id"],
                               "2026-06-01T00:00:00Z", "2026-08-01T00:00:00Z",
                               bonus_bps=bonus_bps, name="Summer")
    batch = commit_batch(merchant["id"], program["id"], 1, unit_load_cents)
    card = activate_card(get_batch_cards(batch["id"])[0]["id"])
    return merchant, program, campaign, card
