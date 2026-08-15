"""Promotional offers: closed-window overlap, enrollment gates, rollover
treatments, sweep-driven notices, and lifecycle independence (PRD §2.4, §3.5)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    account_action,
    create_effective_sheet,
    create_product,
    create_promo,
    enroll_promo,
    list_account_notices,
    open_account,
    set_clock,
    single_tier,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ANALYST = TEST_USERS["analyst_headers"]
BANKER = TEST_USERS["banker_headers"]


def _promo_product(code: str):
    return create_product(product_code=code, product_class="MONEY_MARKET", term_months=0,
                          tier_application="MARGINAL", rate_cap_bp=600,
                          allows_promos=True)


def test_promo_window_touching_boundaries_conflict(api, analyst_headers):
    """PRD §3.5: "the closed window must not intersect any `SCHEDULED` or
    `ACTIVE` offer for the same pair — because the interval is closed, offers
    that merely touch on a boundary date still conflict (else
    `ERR_PROMO_WINDOW_OVERLAP`)."

    Design: Difficulty/resource_temporal_overlap/promo_window_closed_interval_touch_conflicts
    """
    product = _promo_product("OVP")
    create_promo(product["id"], promo_rate_bp=500, enrollment_start="2026-08-01",
                 enrollment_end="2026-08-31")
    # Second offer starts exactly on the first offer's enrollment_end: the
    # closed intervals intersect on 2026-08-31.
    touching = create_promo(product["id"], publish=False, promo_rate_bp=450,
                            enrollment_start="2026-08-31", enrollment_end="2026-09-15")
    resp = api.publish_promotional_offer(touching["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_PROMO_WINDOW_OVERLAP, 409)


def test_promo_window_one_day_apart_is_allowed(api, analyst_headers):
    """PRD §3.5: "Publishing moves `DRAFT → SCHEDULED` after two checks:
    `enrollment_start` must not fall after `enrollment_end` (else
    `ERR_INVALID_REQUEST`), and the closed window must not intersect any
    `SCHEDULED` or `ACTIVE` offer for the same pair — because the interval is
    closed, offers that merely touch on a boundary date still conflict (else
    `ERR_PROMO_WINDOW_OVERLAP`)."

    Design: Difficulty/resource_temporal_overlap/promo_window_closed_interval_touch_conflicts
    """
    product = _promo_product("OVP")
    create_promo(product["id"], promo_rate_bp=500, enrollment_start="2026-08-01",
                 enrollment_end="2026-08-31")
    # Starting one day after the first window's end: no shared date.
    apart = create_promo(product["id"], publish=False, promo_rate_bp=450,
                         enrollment_start="2026-09-01", enrollment_end="2026-09-15")
    published = validate_success(api.publish_promotional_offer(apart["id"], analyst_headers))
    assert published["status"] == "SCHEDULED"


def test_promo_close_from_draft_returns_promo_invalid_state(api, analyst_headers):
    """PRD §3.5: "Offer actions from incompatible states — closing a `DRAFT`,
    publishing an `ACTIVE` — are rejected with `ERR_PROMO_INVALID_STATE`."

    Design: Corner/state_machines/promo_close_from_draft_and_terminal_lockdown
    """
    product = _promo_product("IV4")
    draft = create_promo(product["id"], publish=False, enrollment_start="2026-08-01",
                         enrollment_end="2026-08-31")
    resp = api.close_promotional_offer(draft["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_PROMO_INVALID_STATE, 409)


def _window_scenario(api):
    """EFFECTIVE sheet (150 bp) for P-MMAE plus offer PE published over the
    window [2026-08-20, 2026-08-31] (SCHEDULED until the sweep reaches the
    window start) and two open accounts."""
    product = _promo_product("MMAE")
    create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                           tiers=single_tier(150))
    offer = create_promo(product["id"], promo_rate_bp=500, promo_term_days=30,
                         enrollment_start="2026-08-20", enrollment_end="2026-08-31",
                         rollover_treatment="ROLL_TO_SHEET")
    a1 = open_account(product["id"], opening_balance_cents=1_000_000, customer_ref="CE1")
    a2 = open_account(product["id"], opening_balance_cents=1_000_000, customer_ref="CE2")
    return product, offer, a1, a2


def test_promo_enroll_before_window_and_when_active(api, banker_headers):
    """PRD §3.5: "the offer must be `ACTIVE`, logical today must lie inside
    the closed enrollment window, and the offer's product and market must
    match the account's (else `ERR_PROMO_NOT_ENROLLABLE`); and the account's
    `balance_cents` must be at least the offer's `min_opening_balance_cents`
    (else `ERR_PROMO_MIN_BALANCE_UNMET`)."
    PRD §3.5: "On success the account's `rate_source` becomes `PROMO`,
    `promo_offer_id` is recorded, `promo_end_date` is set to the enrollment
    date plus the offer's `promo_term_days`, the rate is recomputed, and the
    version bumps."
    PRD §2.4: "offers in `SCHEDULED` whose `enrollment_start` has been reached
    become `ACTIVE`; offers whose `enrollment_end` has passed — whether still
    `SCHEDULED` or already `ACTIVE` — become `EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/promo_enroll_requires_offer_active_and_window
    """
    _, offer, a1, _ = _window_scenario(api)

    # 2026-08-15: the offer is published but the window has not started.
    resp = api.deposit_account_action(
        a1["id"], {"action": "ENROLL_PROMO", "promo_offer_id": offer["id"]}, banker_headers)
    validate_error(resp, ApiErrorId.ERR_PROMO_NOT_ENROLLABLE, 422)

    # The sweep flips the offer to ACTIVE at the window start.
    set_clock("2026-08-20")
    enrolled = enroll_promo(a1["id"], offer["id"])
    assert enrolled["rate_source"] == "PROMO"
    assert enrolled["promo_offer_id"] == offer["id"]
    assert enrolled["promo_end_date"] == "2026-09-19"
    assert enrolled["current_rate_bp"] == 500


def test_promo_enroll_after_window_returns_not_enrollable(api, banker_headers):
    """PRD §3.5: "the offer must be `ACTIVE`, logical today must lie inside
    the closed enrollment window, and the offer's product and market must
    match the account's (else `ERR_PROMO_NOT_ENROLLABLE`); and the account's
    `balance_cents` must be at least the offer's `min_opening_balance_cents`
    (else `ERR_PROMO_MIN_BALANCE_UNMET`)."
    PRD §2.4: "offers in `SCHEDULED` whose `enrollment_start` has been reached
    become `ACTIVE`; offers whose `enrollment_end` has passed — whether still
    `SCHEDULED` or already `ACTIVE` — become `EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/promo_enroll_requires_offer_active_and_window
    """
    _, offer, _, a2 = _window_scenario(api)
    set_clock("2026-09-01")  # window [2026-08-20, 2026-08-31] fully passed
    offer_now = validate_success(api.get_promotional_offer(offer["id"], ANALYST))
    assert offer_now["status"] == "EXPIRED"
    resp = api.deposit_account_action(
        a2["id"], {"action": "ENROLL_PROMO", "promo_offer_id": offer["id"]}, banker_headers)
    validate_error(resp, ApiErrorId.ERR_PROMO_NOT_ENROLLABLE, 422)


def test_promo_min_balance_boundary(api, banker_headers):
    """PRD §3.5: "and the account's `balance_cents` must be at least the
    offer's `min_opening_balance_cents` (else `ERR_PROMO_MIN_BALANCE_UNMET`)."

    Design: Corner/validations/promo_min_balance_boundary
    """
    product = _promo_product("PM")
    create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                           tiers=single_tier(150))
    offer = create_promo(product["id"], promo_rate_bp=500, promo_term_days=30,
                         enrollment_start="2026-08-01", enrollment_end="2026-08-31",
                         min_opening_balance_cents=1_000_000)
    set_clock("2026-08-16")  # sweep flips the offer ACTIVE (window already open)
    at_min = open_account(product["id"], opening_balance_cents=1_000_000,
                          customer_ref="CP1")
    below_min = open_account(product["id"], opening_balance_cents=999_999,
                             customer_ref="CP2")

    enrolled = enroll_promo(at_min["id"], offer["id"])
    assert enrolled["rate_source"] == "PROMO"

    resp = api.deposit_account_action(
        below_min["id"], {"action": "ENROLL_PROMO", "promo_offer_id": offer["id"]},
        banker_headers)
    validate_error(resp, ApiErrorId.ERR_PROMO_MIN_BALANCE_UNMET, 422)


def test_enroll_with_bogus_promo_returns_promo_not_found(api, banker_headers):
    """PRD §2.8: "Foreign keys carried in request bodies are validated after
    path existence, each mapping to its own HTTP 422 error: a missing
    `product_id` reference yields `ERR_PRODUCT_NOT_FOUND`, a missing
    `sheet_id` yields `ERR_SHEET_NOT_FOUND`, a missing `account_id` yields
    `ERR_ACCOUNT_NOT_FOUND`, a missing `promo_offer_id` yields
    `ERR_PROMO_NOT_FOUND`, and a missing `bundle_id` yields
    `ERR_BUNDLE_NOT_FOUND`."

    Design: Corner/errors/enroll_with_bogus_promo_returns_promo_not_found
    """
    product = create_product(product_code="PNF")
    create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                           tiers=single_tier(100))
    account = open_account(product["id"], opening_balance_cents=1_000_000,
                           customer_ref="CPF")
    resp = api.deposit_account_action(
        account["id"], {"action": "ENROLL_PROMO", "promo_offer_id": NON_EXISTENT_UUID},
        banker_headers)
    validate_error(resp, ApiErrorId.ERR_PROMO_NOT_FOUND, 422)


def _parallel_scenario(api):
    """P-MMAP with an EFFECTIVE 150 bp sheet and offer PR1 [08-15, 09-30]
    (term 30, ROLL_TO_SHEET); account AP enrolled into the promo at
    2026-08-16 (promo_end_date 2026-09-15), then FROZEN."""
    product = _promo_product("MMAP")
    create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                           tiers=single_tier(150))
    offer = create_promo(product["id"], promo_rate_bp=500, promo_term_days=30,
                         enrollment_start="2026-08-15", enrollment_end="2026-09-30",
                         rollover_treatment="ROLL_TO_SHEET")
    set_clock("2026-08-16")  # offer ACTIVE
    account = open_account(product["id"], opening_balance_cents=1_000_000,
                           customer_ref="CP")
    enrolled = enroll_promo(account["id"], offer["id"])
    return product, offer, enrolled


def test_freeze_preserves_promo_rate_source(api, banker_headers):
    """PRD §3.5: "`FREEZE` moves `OPEN → FROZEN`, `UNFREEZE` moves `FROZEN →
    OPEN`, and `CLOSE` moves `OPEN` or `FROZEN` to the terminal `CLOSED`."
    PRD §3.5: "On success the account's `rate_source` becomes `PROMO`,
    `promo_offer_id` is recorded, `promo_end_date` is set to the enrollment
    date plus the offer's `promo_term_days`, the rate is recomputed, and the
    version bumps."

    The two dimensions evolve independently: freezing the lifecycle leaves the
    promo pricing in place.

    Design: Difficulty/non_linear_state_machine/account_parallel_dimensions_independent
    """
    _, _, enrolled = _parallel_scenario(api)
    assert enrolled["rate_source"] == "PROMO"
    assert enrolled["current_rate_bp"] == 500

    frozen = account_action(enrolled["id"], "FREEZE")
    assert frozen["lifecycle"] == "FROZEN"
    assert frozen["rate_source"] == "PROMO"
    assert frozen["current_rate_bp"] == 500


def test_frozen_account_still_rolls_over_promo(api, banker_headers):
    """PRD §2.4: "Per-account promo rollover for accounts whose
    `promo_end_date` has passed, including `RENEW_THEN_SHEET` extension (see
    §3.5)." — the sweep's rollover step carries no lifecycle gate.
    PRD §3.5: "under `ROLL_TO_SHEET` — or under `RENEW_THEN_SHEET` when the
    offer is no longer active — the account returns to `SHEET`, its promo
    fields clear, the rate recomputes from the sheet, and the version bumps."

    Design: Difficulty/non_linear_state_machine/account_parallel_dimensions_independent
    """
    _, _, enrolled = _parallel_scenario(api)
    account_action(enrolled["id"], "FREEZE")

    set_clock("2026-09-20")  # past promo_end_date 2026-09-15
    account = validate_success(api.get_deposit_account(enrolled["id"], banker_headers))
    assert account["lifecycle"] == "FROZEN"     # lifecycle untouched by the sweep
    assert account["rate_source"] == "SHEET"    # rollover fired anyway
    assert account["current_rate_bp"] == 150
    assert account["promo_offer_id"] is None


def _rollover_scenario(api, promo_term_days=30, enrollment_end="2026-09-14"):
    """P-MMAR with EFFECTIVE 150 bp sheet; offer PR2 (rate 500, ROLL_TO_SHEET)
    over [2026-08-15, enrollment_end]; account AR enrolled at 2026-08-16 once
    the sweep has flipped the offer ACTIVE."""
    product = _promo_product("MMAR")
    create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                           tiers=single_tier(150))
    offer = create_promo(product["id"], promo_rate_bp=500,
                         promo_term_days=promo_term_days,
                         enrollment_start="2026-08-15", enrollment_end=enrollment_end,
                         rollover_treatment="ROLL_TO_SHEET")
    set_clock("2026-08-16")
    account = open_account(product["id"], opening_balance_cents=1_000_000,
                           customer_ref="CR")
    enrolled = enroll_promo(account["id"], offer["id"])
    return product, offer, enrolled


def test_promo_rollover_to_sheet_with_adverse_notice(api, banker_headers,
                                                     compliance_headers):
    """PRD §3.5: "under `ROLL_TO_SHEET` — or under `RENEW_THEN_SHEET` when the
    offer is no longer active — the account returns to `SHEET`, its promo
    fields clear, the rate recomputes from the sheet, and the version bumps.
    A rollover that drops the rate by ten basis points or more raises a
    `RATE_CHANGE_ADVERSE` notice due five days later."
    PRD §2.4: "offers whose `enrollment_end` has passed — whether still
    `SCHEDULED` or already `ACTIVE` — become `EXPIRED`."

    Design: Difficulty/transitive_cascade/clock_sweep_promo_rollover_cascade
    """
    _, offer, enrolled = _rollover_scenario(api)
    assert enrolled["rate_source"] == "PROMO"
    assert enrolled["promo_end_date"] == "2026-09-15"  # 2026-08-16 + 30 days

    set_clock("2026-09-16")  # past promo_end_date
    account = validate_success(api.get_deposit_account(enrolled["id"], banker_headers))
    assert account["rate_source"] == "SHEET"
    assert account["promo_offer_id"] is None
    assert account["current_rate_bp"] == 150

    adverse = [n for n in list_account_notices(account["id"])
               if n["notice_type"] == "RATE_CHANGE_ADVERSE"]
    assert len(adverse) == 1
    assert adverse[0]["required_by_date"] == "2026-09-21"  # trigger date + 5

    offer_now = validate_success(api.get_promotional_offer(offer["id"], ANALYST))
    assert offer_now["status"] == "EXPIRED"  # today 2026-09-16 > window end 2026-09-14


def test_promo_expiry_notice_created_thirty_days_before_end(api, banker_headers):
    """PRD §2.9: "`PROMO_EXPIRY` — account-level notices created by the time
    sweep thirty days before an enrolled account's `promo_end_date`; the
    required date is `promo_end_date` minus thirty days."
    PRD §2.4: "`PROMO_EXPIRY` notices are created for accounts whose
    `promo_end_date` is exactly thirty days in the future (see §2.9)."

    Design: Difficulty/transitive_cascade/clock_sweep_promo_rollover_cascade
    """
    # Term 31 days so the "exactly thirty days before promo_end_date" sweep
    # day (2026-08-17) falls strictly after the enrollment day (2026-08-16).
    _, _, enrolled = _rollover_scenario(api, promo_term_days=31,
                                        enrollment_end="2026-09-30")
    assert enrolled["promo_end_date"] == "2026-09-16"

    set_clock("2026-08-17")  # promo_end 2026-09-16 is exactly 30 days out
    expiry = [n for n in list_account_notices(enrolled["id"])
              if n["notice_type"] == "PROMO_EXPIRY"]
    assert len(expiry) == 1
    assert expiry[0]["required_by_date"] == "2026-08-17"  # promo_end - 30 days

    # The rollover itself has not fired yet.
    account = validate_success(api.get_deposit_account(enrolled["id"], banker_headers))
    assert account["rate_source"] == "PROMO"


def test_promo_renew_then_sheet_rollover_treatment(api, banker_headers,
                                                   analyst_headers):
    """PRD §3.5: "When logical today passes an account's `promo_end_date`, the
    offer's `rollover_treatment` decides: under `RENEW_THEN_SHEET` with the
    offer still `ACTIVE`, the account's `promo_end_date` extends by another
    `promo_term_days` and the account stays on `PROMO` with no transition;
    under `ROLL_TO_SHEET` — or under `RENEW_THEN_SHEET` when the offer is no
    longer active — the account returns to `SHEET`, its promo fields clear,
    the rate recomputes from the sheet, and the version bumps."
    PRD §3.5: "An analyst may also close an `ACTIVE` offer, moving it to
    `CLOSED`: enrollment stops immediately, but accounts already on the promo
    keep their rate until their own `promo_end_date`."

    Design: Corner/complexity_layers/promo_renew_then_sheet_rollover_treatment
    """
    product = _promo_product("RNW")
    create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                           tiers=single_tier(150))
    offer = create_promo(product["id"], promo_rate_bp=500, promo_term_days=30,
                         enrollment_start="2026-08-15", enrollment_end="2026-09-30",
                         rollover_treatment="RENEW_THEN_SHEET")
    set_clock("2026-08-16")
    account = open_account(product["id"], opening_balance_cents=1_000_000,
                           customer_ref="CRN")
    enrolled = enroll_promo(account["id"], offer["id"])
    assert enrolled["promo_end_date"] == "2026-09-15"

    # First rollover with the offer still ACTIVE: renew, stay on PROMO.
    set_clock("2026-09-20")
    renewed = validate_success(api.get_deposit_account(account["id"], banker_headers))
    assert renewed["rate_source"] == "PROMO"
    assert renewed["promo_end_date"] == "2026-10-15"  # extended by promo_term_days
    assert renewed["current_rate_bp"] == 500

    # Closing the offer does not disturb the enrolled account mid-term.
    closed = validate_success(api.close_promotional_offer(offer["id"], analyst_headers))
    assert closed["status"] == "CLOSED"

    # Second rollover with the offer no longer ACTIVE: fall back to sheet.
    set_clock("2026-10-20")
    rolled = validate_success(api.get_deposit_account(account["id"], banker_headers))
    assert rolled["rate_source"] == "SHEET"
    assert rolled["current_rate_bp"] == 150
    assert rolled["promo_offer_id"] is None
