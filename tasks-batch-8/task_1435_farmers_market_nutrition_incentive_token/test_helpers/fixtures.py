"""Composite setup helpers.

Every test starts against a fresh server (the runner restarts it per test), so
each fixture builds its preconditions from scratch via PRD-declared endpoints.
Setup calls use the lenient get_success_data validator so a broken precondition
fails loudly at the step that broke, inside the calling test's traceback.

Identity threading: Vendor and Shopper are entity-backed roles, so every
ownership-gated call uses make_vendor_headers(entity["id"]) /
make_shopper_headers(entity["id"]) — never the shared fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from . import constants as C
from .factories import (
    create_program_payload, create_market_payload, create_vendor_payload,
    create_shopper_payload, create_market_day_payload, create_token_batch_payload,
    create_issuance_payload, create_submission_payload,
    create_settlement_run_payload,
)
from .test_users import TEST_USERS, make_vendor_headers

ADMIN = TEST_USERS["program_admin_headers"]
MANAGER = TEST_USERS["market_manager_headers"]
BOOTH = TEST_USERS["booth_operator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity builders
# ---------------------------------------------------------------------------

def create_program(pool_cents=100000,
                   name="P", season_start=C.SEASON_START, season_end=C.SEASON_END) -> dict:
    resp = api_client.create_program(
        create_program_payload(name=name, season_start=season_start,
                               season_end=season_end, match_pool_budget_cents=pool_cents),
        ADMIN)
    return get_success_data(resp)


def create_market(program_id, name="M", city="C") -> dict:
    resp = api_client.create_market(
        create_market_payload(program_id=program_id, name=name, city=city), ADMIN)
    return get_success_data(resp)


def create_batch(market_id, kind, denomination_cents, serial_start, serial_end,
                 activate=True) -> dict:
    batch = get_success_data(api_client.create_token_batch(
        create_token_batch_payload(market_id=market_id, kind=kind,
                                   denomination_cents=denomination_cents,
                                   serial_start=serial_start, serial_end=serial_end),
        ADMIN))
    if activate:
        batch = get_success_data(api_client.activate_token_batch(batch["id"], ADMIN))
    return batch


def create_standard_batches(market_id, match_serial_end=C.MATCH_SERIAL_END,
                            activate_match=True) -> tuple:
    """The standard three-batch supply: BASE-500, BASE-100, MATCH-100."""
    b5 = create_batch(market_id, "BASE", 500, C.BASE500_SERIAL_START, C.BASE500_SERIAL_END)
    b1 = create_batch(market_id, "BASE", 100, C.BASE100_SERIAL_START, C.BASE100_SERIAL_END)
    bm = create_batch(market_id, "MATCH", 100, C.MATCH_SERIAL_START, match_serial_end,
                      activate=activate_match)
    return b5, b1, bm


def create_verified_shopper(program_id, ref="EBT-1", benefit_type="SNAP") -> dict:
    """Enroll (BoothOperator) + verify (ProgramAdmin). Returns ACTIVE shopper."""
    shopper = get_success_data(api_client.create_shopper(
        create_shopper_payload(program_id=program_id, external_benefit_ref=ref,
                               benefit_type=benefit_type),
        BOOTH))
    return get_success_data(api_client.verify_shopper(shopper["id"], ADMIN))


def create_market_day(market_id, date=C.DAY_DATE, opens_at=C.DAY_OPENS_AT,
                      closes_at=C.DAY_CLOSES_AT) -> dict:
    """SCHEDULED market day."""
    return get_success_data(api_client.create_market_day(
        create_market_day_payload(market_id=market_id, date=date,
                                  opens_at=opens_at, closes_at=closes_at),
        MANAGER))


def create_open_day(market_id, date=C.DAY_DATE, opens_at=C.DAY_OPENS_AT,
                    closes_at=C.DAY_CLOSES_AT) -> dict:
    """Market day walked SCHEDULED -> OPEN (requires clock date == day date)."""
    day = create_market_day(market_id, date=date, opens_at=opens_at, closes_at=closes_at)
    return get_success_data(api_client.open_market_day(day["id"], MANAGER))


def create_active_vendor(market_id, legal_name="V", stall_number="S1") -> dict:
    """Vendor walked PENDING -> ACTIVE."""
    vendor = get_success_data(api_client.create_vendor(
        create_vendor_payload(market_id=market_id, legal_name=legal_name,
                              stall_number=stall_number),
        ADMIN))
    return get_success_data(api_client.approve_vendor(vendor["id"], ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: composite scenario
# ---------------------------------------------------------------------------

def setup_booth_scenario(pool_cents=100000, benefit_type="SNAP", benefit_ref="EBT-1",
                         with_vendor=True, open_day=True,
                         match_batch_active=True, match_serial_end=C.MATCH_SERIAL_END,
                         program_name="P", market_name="M") -> dict:
    """Program + market + three ACTIVE batches + ACTIVE shopper (+ OPEN day + ACTIVE vendor).

    Returns a dict: program, market, batch_base500, batch_base100, batch_match,
    shopper, market_day (or None), vendor (or None).
    """
    program = create_program(pool_cents=pool_cents, name=program_name)
    market = create_market(program["id"], name=market_name)
    b5, b1, bm = create_standard_batches(market["id"],
                                         match_serial_end=match_serial_end,
                                         activate_match=match_batch_active)
    shopper = create_verified_shopper(program["id"], ref=benefit_ref,
                                      benefit_type=benefit_type)
    day = create_open_day(market["id"]) if open_day else None
    vendor = create_active_vendor(market["id"]) if with_vendor else None
    return {
        "program": program,
        "market": market,
        "batch_base500": b5,
        "batch_base100": b1,
        "batch_match": bm,
        "shopper": shopper,
        "market_day": day,
        "vendor": vendor,
    }


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------

def issue_tokens(shopper_id, market_day_id, benefit_charged_cents) -> tuple:
    """Create an issuance (reading the shopper's current version for the OCC
    guard), then read back its minted tokens ordered by serial ascending.
    Returns (issuance, tokens)."""
    shopper = get_success_data(api_client.get_shopper(shopper_id, BOOTH))
    issuance = get_success_data(api_client.create_issuance(
        create_issuance_payload(shopper_id=shopper_id, market_day_id=market_day_id,
                                benefit_charged_cents=benefit_charged_cents,
                                expected_shopper_version=shopper["version"]),
        BOOTH))
    return issuance, minted_tokens(issuance["id"])


def minted_tokens(issuance_id) -> list:
    """All tokens of an issuance, serial_number ascending (full page)."""
    resp = api_client.list_tokens(BOOTH, params={"issuance_id": issuance_id, "limit": 100})
    data, _meta = validate_paginated(resp)
    return data


def redeem_serial(vendor_id, serial_number) -> dict:
    """Vendor redeems one serial; returns the REDEEMED token."""
    return get_success_data(api_client.redeem_token(serial_number, make_vendor_headers(vendor_id)))


def redeem_serials(vendor_id, serial_numbers) -> list:
    return [redeem_serial(vendor_id, s) for s in serial_numbers]


def create_submission(vendor_id, market_day_id, token_ids) -> dict:
    return get_success_data(api_client.create_submission(
        create_submission_payload(market_day_id=market_day_id, token_ids=list(token_ids)),
        make_vendor_headers(vendor_id)))


def close_day(market_day_id) -> dict:
    return get_success_data(api_client.close_market_day(market_day_id, MANAGER))


def verify_submission(submission_id, outcome="VERIFIED") -> dict:
    return get_success_data(api_client.verify_submission(submission_id, outcome, MANAGER))


def decide_submission(submission_id, outcome) -> dict:
    return get_success_data(api_client.decide_submission(submission_id, outcome, ADMIN))


def current_program_version(program_id) -> int:
    return get_success_data(api_client.get_program(program_id, ADMIN))["version"]


def run_settlement(program_id, cutoff_at="2026-08-31T23:59:59Z") -> dict:
    """Sweep with a fresh OCC read of the program version."""
    version = current_program_version(program_id)
    return get_success_data(api_client.create_settlement_run(
        create_settlement_run_payload(program_id=program_id, cutoff_at=cutoff_at,
                                      expected_program_version=version),
        ADMIN))


# ---------------------------------------------------------------------------
# Tier 4/5: full reimbursement pipeline
# ---------------------------------------------------------------------------

def setup_submitted_claim(charge=300, redeem_count=1, pool_cents=100000) -> dict:
    """Booth scenario + issuance + the first `redeem_count` base-100 tokens
    (serials 200001+) redeemed by the vendor + claim created while day OPEN.
    Returns scenario dict augmented with issuance, tokens, submission."""
    sc = setup_booth_scenario(pool_cents=pool_cents)
    issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], charge)
    vend_id = sc["vendor"]["id"]
    serials = [t["serial_number"] for t in tokens[:redeem_count]]
    redeem_serials(vend_id, serials)
    claimed = [t for t in tokens if t["serial_number"] in set(serials)]
    submission = create_submission(vend_id, sc["market_day"]["id"],
                                   [t["id"] for t in claimed])
    sc.update({"issuance": issuance, "tokens": tokens,
               "claimed_tokens": claimed, "submission": submission})
    return sc


def setup_approved_claim(charge=200, token_count=2, pool_cents=100000) -> dict:
    """Full pipeline through APPROVED: issuance, redeem, claim, close, verify,
    approve. Returns scenario dict augmented with issuance, tokens, submission."""
    sc = setup_booth_scenario(pool_cents=pool_cents)
    issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], charge)
    vend_id = sc["vendor"]["id"]
    claimed = tokens[:token_count]
    redeem_serials(vend_id, [t["serial_number"] for t in claimed])
    submission = create_submission(vend_id, sc["market_day"]["id"],
                                   [t["id"] for t in claimed])
    close_day(sc["market_day"]["id"])
    verify_submission(submission["id"], "VERIFIED")
    sc["submission"] = decide_submission(submission["id"], "APPROVED")
    sc.update({"issuance": issuance, "tokens": tokens, "claimed_tokens": claimed})
    return sc
