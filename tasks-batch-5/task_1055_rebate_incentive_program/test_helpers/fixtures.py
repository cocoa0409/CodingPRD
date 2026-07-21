"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because each test starts against an empty database with the logical clock at its
startup default. Setup calls use the lenient validator so a broken precondition
surfaces as a clear setup failure rather than a confusing assertion.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    FINANCE_USER_ID,
    PROCESSOR_USER_ID,
    TEST_DEFAULTS,
)
from .factories import (
    create_budget_adjustment_payload,
    create_claim_payload,
    create_claimant_payload,
    create_fraud_case_payload,
    create_offer_payload,
    create_payout_payload,
    create_program_payload,
    create_receipt_payload,
    next_serial,
    receipt_line,
)
from .test_users import (
    TEST_USERS,
    make_claimant_headers,
    make_finance_headers,
    make_processor_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
PROCESSOR = TEST_USERS["claims_processor_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
FRAUD = TEST_USERS["fraud_analyst_headers"]


# --------------------------------------------------------------------------- #
# Tier 0: single-step primitives
# --------------------------------------------------------------------------- #

def set_clock(to_iso8601: str) -> str:
    """Drive the server's logical clock; returns the resulting current_utc."""
    data = get_success_data(api_client.set_clock(to_iso8601, ADMIN))
    return data["current_utc"]


def create_program(**overrides) -> dict:
    return get_success_data(api_client.create_program(create_program_payload(**overrides), ADMIN))


def create_active_program(**overrides) -> dict:
    program = create_program(**overrides)
    return get_success_data(api_client.activate_program(program["id"], ADMIN))


def create_offer(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_offer(create_offer_payload(program_id, **overrides), ADMIN)
    )


def create_published_offer(program_id: str, **overrides) -> dict:
    offer = create_offer(program_id, **overrides)
    return get_success_data(api_client.publish_offer(offer["id"], ADMIN))


def create_claimant(**overrides) -> dict:
    return get_success_data(
        api_client.create_claimant(create_claimant_payload(**overrides), ADMIN)
    )


def create_dealer_claimant(**overrides) -> dict:
    payload = {
        "type": "DEALER",
        "legal_name": "Test Dealer LLC",
        "email": "ap@testdealer.example",
        "mailing_state": TEST_DEFAULTS["DEALER_MAILING_STATE"],
    }
    payload.update(overrides)
    return create_claimant(**payload)


def create_consumer_claimant(**overrides) -> dict:
    payload = {
        "type": "CONSUMER",
        "legal_name": "Test Consumer",
        "email": "me@testconsumer.example",
        "mailing_state": TEST_DEFAULTS["CONSUMER_MAILING_STATE"],
    }
    payload.update(overrides)
    return create_claimant(**payload)


def open_claim(offer_id: str, claimant: dict) -> dict:
    """Open a DRAFT claim, acting as the claimant itself."""
    return get_success_data(
        api_client.create_claim(
            create_claim_payload(offer_id, claimant["id"]), make_claimant_headers(claimant)
        )
    )


def attach_receipt(claim_id: str, claimant: dict, **overrides) -> dict:
    """Attach a proof-of-purchase receipt to a DRAFT claim."""
    return get_success_data(
        api_client.create_receipt(
            claim_id, create_receipt_payload(**overrides), make_claimant_headers(claimant)
        )
    )


def validate_receipt(receipt_id: str, processor_user_id: str = PROCESSOR_USER_ID) -> dict:
    return get_success_data(
        api_client.validate_receipt(receipt_id, make_processor_headers(processor_user_id))
    )


def read_program(program_id: str) -> dict:
    return get_success_data(api_client.get_program(program_id, ADMIN))


def read_offer(offer_id: str) -> dict:
    return get_success_data(api_client.get_offer(offer_id, ADMIN))


def read_claimant(claimant_id: str) -> dict:
    return get_success_data(api_client.get_claimant(claimant_id, ADMIN))


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, ADMIN))


def read_receipt(receipt_id: str) -> dict:
    return get_success_data(api_client.get_receipt(receipt_id, ADMIN))


def read_payout(payout_id: str) -> dict:
    return get_success_data(api_client.get_payout(payout_id, ADMIN))


def read_virtual_card(card_id: str) -> dict:
    return get_success_data(api_client.get_virtual_card(card_id, ADMIN))


def read_fraud_case(case_id: str) -> dict:
    return get_success_data(api_client.get_fraud_case(case_id, ADMIN))


def read_program_report(program_id: str) -> dict:
    return get_success_data(api_client.get_program_report(program_id, ADMIN))


def list_ledger(program_id: str = None, claim_id: str = None, entry_type: str = None) -> list:
    params = {"limit": 100}
    if program_id:
        params["program_id"] = program_id
    if claim_id:
        params["claim_id"] = claim_id
    if entry_type:
        params["entry_type"] = entry_type
    return get_success_data(api_client.list_budget_entries(ADMIN, params=params))


def find_card_for_payout(payout_id: str) -> dict:
    cards = get_success_data(
        api_client.list_virtual_cards(ADMIN, params={"payout_id": payout_id})
    )
    assert cards, f"Setup failed: no virtual card materialised for payout {payout_id}"
    return cards[0]


# --------------------------------------------------------------------------- #
# Tier 1/2: program + offer + claimant preconditions
# --------------------------------------------------------------------------- #

def setup_catalogue(
    clock: str = TEST_DEFAULTS["CLOCK"],
    budget_total_cents: int = TEST_DEFAULTS["BUDGET_TOTAL_CENTS"],
    channel: str = "DEALER",
    claimant_type: str = "DEALER",
    program_overrides: dict = None,
    offer_overrides: dict = None,
    claimant_overrides: dict = None,
) -> dict:
    """Active program + published offer + active claimant.

    Returns {"program", "offer", "claimant", "headers"} where headers are the
    claimant-facing headers bound to the claimant's own id.
    """
    if clock:
        set_clock(clock)
    program = create_active_program(
        budget_total_cents=budget_total_cents, **(program_overrides or {})
    )
    offer_kwargs = {"channel": channel}
    if channel == "CONSUMER":
        offer_kwargs["sku_scope"] = TEST_DEFAULTS["CONSUMER_SKU_SCOPE"]
    offer_kwargs.update(offer_overrides or {})
    offer = create_published_offer(program["id"], **offer_kwargs)

    if claimant_type == "DEALER":
        claimant = create_dealer_claimant(**(claimant_overrides or {}))
    else:
        claimant = create_consumer_claimant(**(claimant_overrides or {}))

    return {
        "program": program,
        "offer": offer,
        "claimant": claimant,
        "headers": make_claimant_headers(claimant),
    }


def setup_draft_claim(
    lines: list = None,
    purchase_date: str = TEST_DEFAULTS["PURCHASE_DATE"],
    serial_number: str = None,
    with_receipt: bool = True,
    **catalogue_kwargs,
) -> dict:
    """Catalogue + one DRAFT claim, optionally carrying one receipt.

    Returns the catalogue dict extended with "claim" and (when a receipt was
    attached) "receipt".
    """
    ctx = setup_catalogue(**catalogue_kwargs)
    ctx["claim"] = open_claim(ctx["offer"]["id"], ctx["claimant"])
    if with_receipt:
        retailer = (
            TEST_DEFAULTS["RETAILER_CONSUMER"]
            if ctx["claimant"]["type"] == "CONSUMER"
            else TEST_DEFAULTS["RETAILER_DEALER"]
        )
        ctx["receipt"] = attach_receipt(
            ctx["claim"]["id"],
            ctx["claimant"],
            serial_number=serial_number or next_serial(),
            purchase_date=purchase_date,
            retailer_name=retailer,
            lines=lines or [receipt_line()],
        )
    return ctx


def setup_submitted_claim(**kwargs) -> dict:
    """Catalogue + a claim carried through DRAFT -> SUBMITTED."""
    ctx = setup_draft_claim(**kwargs)
    ctx["claim"] = get_success_data(
        api_client.submit_claim(ctx["claim"]["id"], ctx["headers"])
    )
    return ctx


def setup_claim_under_review(validate_receipt_flag: bool = True, **kwargs) -> dict:
    """Catalogue + a claim in UNDER_REVIEW, with its receipt validated by default."""
    ctx = setup_submitted_claim(**kwargs)
    ctx["claim"] = get_success_data(api_client.review_claim(ctx["claim"]["id"], PROCESSOR))
    if validate_receipt_flag and "receipt" in ctx:
        ctx["receipt"] = validate_receipt(ctx["receipt"]["id"])
    return ctx


def setup_approved_claim(approver_user_id: str = PROCESSOR_USER_ID, **kwargs) -> dict:
    """Catalogue + an APPROVED claim. Adds "claim_version" observed at approval."""
    ctx = setup_claim_under_review(**kwargs)
    ctx["claim"] = get_success_data(
        api_client.approve_claim(ctx["claim"]["id"], make_processor_headers(approver_user_id))
    )
    ctx["claim_version"] = ctx["claim"]["version"]
    ctx["approver_user_id"] = approver_user_id
    return ctx


# --------------------------------------------------------------------------- #
# Tier 3: disbursement lifecycle shortcuts
# --------------------------------------------------------------------------- #

def setup_pending_payout(method: str = "CHECK", **kwargs) -> dict:
    """Catalogue + APPROVED claim + a PENDING payout. Adds "payout"."""
    ctx = setup_approved_claim(**kwargs)
    payload = create_payout_payload(ctx["claim_version"])
    if method is not None:
        payload["method"] = method
    ctx["payout"] = get_success_data(
        api_client.create_payout(ctx["claim"]["id"], payload, FINANCE)
    )
    ctx["claim"] = read_claim(ctx["claim"]["id"])
    return ctx


def setup_released_payout(
    method: str = "CHECK",
    check_number: str = "CHK-0001",
    releaser_user_id: str = FINANCE_USER_ID,
    **kwargs,
) -> dict:
    """Catalogue + APPROVED claim + a RELEASED payout. Adds "payout" (and "card")."""
    ctx = setup_pending_payout(method=method, **kwargs)
    release_payload = {"check_number": check_number} if method == "CHECK" else {}
    ctx["payout"] = get_success_data(
        api_client.release_payout(
            ctx["payout"]["id"], make_finance_headers(releaser_user_id), release_payload
        )
    )
    ctx["claim"] = read_claim(ctx["claim"]["id"])
    if ctx["payout"]["method"] == "VIRTUAL_CARD":
        ctx["card"] = find_card_for_payout(ctx["payout"]["id"])
    return ctx


def setup_issued_card(**kwargs) -> dict:
    """A RELEASED VIRTUAL_CARD payout whose card sits in ISSUED.

    Defaults to a CONSUMER claim worth 2500 cents gross (4 x 5000 cents of goods
    at ten percent plus the 500-cent consumer bonus), so the card carries 2450.
    """
    defaults = {
        "channel": "CONSUMER",
        "claimant_type": "CONSUMER",
        "lines": [receipt_line(sku="APPLIANCE-X", quantity=4, unit_price_cents=5000)],
    }
    defaults.update(kwargs)
    return setup_released_payout(method="VIRTUAL_CARD", **defaults)


def setup_activated_card(**kwargs) -> dict:
    """As setup_issued_card, with the card moved ISSUED -> ACTIVATED by its owner."""
    ctx = setup_issued_card(**kwargs)
    ctx["card"] = get_success_data(
        api_client.activate_virtual_card(ctx["card"]["id"], ctx["headers"])
    )
    return ctx


# --------------------------------------------------------------------------- #
# Tier 4: fraud-case workflow
# --------------------------------------------------------------------------- #

def open_fraud_case(claimant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_fraud_case(create_fraud_case_payload(claimant_id, **overrides), FRAUD)
    )


def transition_fraud_case(case_id: str, to_status: str, note: str = None) -> dict:
    payload = {"to_status": to_status}
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.transition_fraud_case(case_id, payload, FRAUD))


def open_case_under_investigation(claimant_id: str, **overrides) -> dict:
    """Analyst-opened case driven OPEN -> UNDER_INVESTIGATION."""
    case = open_fraud_case(claimant_id, **overrides)
    return transition_fraud_case(case["id"], "UNDER_INVESTIGATION")


def substantiate_claimant(claimant_id: str, **overrides) -> dict:
    """Open a case, investigate it and substantiate it, blocking the claimant."""
    case = open_case_under_investigation(claimant_id, **overrides)
    return transition_fraud_case(case["id"], "SUBSTANTIATED")


# --------------------------------------------------------------------------- #
# Tier 5: budget manipulation
# --------------------------------------------------------------------------- #

def adjust_budget(program_id: str, delta_cents: int, memo: str = "Budget adjustment") -> dict:
    program = read_program(program_id)
    return get_success_data(
        api_client.create_budget_adjustment(
            program_id,
            create_budget_adjustment_payload(delta_cents, program["version"], memo=memo),
            ADMIN,
        )
    )


def deny_claim(claim_id: str, reason_code: str = "MISSING_PROOF") -> dict:
    return get_success_data(
        api_client.deny_claim(claim_id, {"reason_code": reason_code}, PROCESSOR)
    )


def appeal_claim(claim_id: str, claimant: dict, appeal_note: str = "Proof attached") -> dict:
    return get_success_data(
        api_client.appeal_claim(
            claim_id, {"appeal_note": appeal_note}, make_claimant_headers(claimant)
        )
    )


def setup_denied_claim(**kwargs) -> dict:
    """Catalogue + a claim carried through to DENIED."""
    ctx = setup_claim_under_review(validate_receipt_flag=False, **kwargs)
    ctx["claim"] = deny_claim(ctx["claim"]["id"])
    return ctx
