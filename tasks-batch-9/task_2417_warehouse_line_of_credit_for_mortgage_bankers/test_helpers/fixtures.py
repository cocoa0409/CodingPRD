"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: each test starts against an empty database.

The canonical chain that most scenarios share is

    set the logical clock -> book the facility (co_1) -> configure one
    CONFORMING rate row -> approve the facility (co_2, four-eyes) -> register
    the custodian -> register and approve the take-out investor -> record the
    commitment -> read the facility version -> book the advance (ca_1) -> file
    the custodian receipt (custodian identity) -> read the paired wire ->
    verify the wire (wo_1) -> fund the advance (ca_1, a different identity from
    the wire's decider)

and the helpers below expose it both step by step and as one call.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    advance_payload,
    commitment_payload,
    covenant_test_payload,
    cure_payment_payload,
    custodian_payload,
    facility_payload,
    investor_payload,
    margin_call_payload,
    product_advance_rate_payload,
    purchase_payload,
    receipt_cure_payload,
    receipt_payload,
    repurchase_payload,
    ship_payload,
    valuation_payload,
    wire_decision_payload,
)
from .test_users import (
    COLLATERAL_ANALYST,
    CONTENT_TYPE_ONLY,
    CREDIT_OFFICER,
    SECOND_CREDIT_OFFICER,
    WIRE_OPERATOR,
    make_borrower_headers,
    make_collateral_analyst_headers,
    make_credit_officer_headers,
    make_custodian_headers,
    make_investor_headers,
    make_wire_operator_headers,
)


class Scenario(dict):
    """A dict of the entities a composite helper built, with attribute access."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - developer error
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


# ─── The logical clock ────────────────────────────────────────────────────────

def set_clock(current_utc: str) -> dict:
    """Move the logical clock. Auth headers are not required on this endpoint."""
    return get_success_data(api_client.set_clock(current_utc, CONTENT_TYPE_ONLY))


# ─── Facility standing-up steps ───────────────────────────────────────────────

def book_facility(creator_user_id: str = "co_1", **overrides) -> dict:
    """`POST /facilities` — lands the facility in `PENDING_APPROVAL`."""
    return get_success_data(
        api_client.create_facility(
            facility_payload(**overrides), make_credit_officer_headers(creator_user_id)
        )
    )


def add_rate_row(facility_id: str, officer_user_id: str = "co_1", **overrides) -> dict:
    """`POST /facilities/{id}/product-advance-rates` — one row per product code."""
    return get_success_data(
        api_client.create_product_advance_rate(
            facility_id,
            product_advance_rate_payload(**overrides),
            make_credit_officer_headers(officer_user_id),
        )
    )


def approve_facility(facility_id: str, approver_user_id: str = "co_2") -> dict:
    """`POST /facilities/{id}/approve` — the approver must differ from the creator."""
    return get_success_data(
        api_client.approve_facility(
            facility_id, make_credit_officer_headers(approver_user_id)
        )
    )


def create_active_facility(
    clock_utc: str = DEFAULT_CLOCK_UTC,
    facility_overrides: dict = None,
    rate_overrides: dict = None,
    extra_rate_rows: list = None,
) -> dict:
    """Clock + booked facility + one rate row + approval. Returns the `ACTIVE` facility."""
    set_clock(clock_utc)
    facility = book_facility(**(facility_overrides or {}))
    add_rate_row(facility["id"], **(rate_overrides or {}))
    for extra in extra_rate_rows or []:
        add_rate_row(facility["id"], **extra)
    return approve_facility(facility["id"])


def suspend_facility(facility_id: str, reason: str = "Annual re-underwriting") -> dict:
    return get_success_data(
        api_client.suspend_facility(facility_id, {"reason": reason}, CREDIT_OFFICER)
    )


def reinstate_facility(facility_id: str) -> dict:
    return get_success_data(api_client.reinstate_facility(facility_id, CREDIT_OFFICER))


def read_facility(facility_id: str) -> dict:
    return get_success_data(api_client.get_facility(facility_id, CREDIT_OFFICER))


def facility_version(facility_id: str) -> int:
    """The facility's current `version`, for the `expected_facility_version` token."""
    return read_facility(facility_id)["version"]


def read_exposure_summary(facility_id: str) -> dict:
    return get_success_data(api_client.get_exposure_summary(facility_id, CREDIT_OFFICER))


# ─── Custodian panel ──────────────────────────────────────────────────────────

def register_custodian(facility_id: str, **overrides) -> dict:
    """`POST /facilities/{id}/custodians` — the row starts `APPROVED`."""
    return get_success_data(
        api_client.create_custodian(
            facility_id, custodian_payload(**overrides), CREDIT_OFFICER
        )
    )


def suspend_custodian(custodian_id: str, reason: str = "SOC 1 exception outstanding") -> dict:
    return get_success_data(
        api_client.suspend_custodian(custodian_id, {"reason": reason}, CREDIT_OFFICER)
    )


# ─── Approved-investor list and commitments ───────────────────────────────────

def register_investor(facility_id: str, approve: bool = True, **overrides) -> dict:
    """`POST /facilities/{id}/investors`, optionally followed by approval."""
    investor = get_success_data(
        api_client.create_investor(
            facility_id, investor_payload(**overrides), CREDIT_OFFICER
        )
    )
    if approve:
        investor = get_success_data(
            api_client.approve_investor(investor["id"], CREDIT_OFFICER)
        )
    return investor


def suspend_investor(investor_id: str, reason: str = "Rating downgrade below policy floor") -> dict:
    return get_success_data(
        api_client.suspend_investor(investor_id, {"reason": reason}, CREDIT_OFFICER)
    )


def record_commitment(facility_id: str, investor_id: str, **overrides) -> dict:
    """`POST /facilities/{id}/commitments` — the forward purchase window."""
    return get_success_data(
        api_client.create_commitment(
            facility_id, commitment_payload(investor_id, **overrides), CREDIT_OFFICER
        )
    )


def withdraw_commitment(commitment_id: str, reason: str = "Investor pulled the bid") -> dict:
    return get_success_data(
        api_client.withdraw_commitment(commitment_id, {"reason": reason}, CREDIT_OFFICER)
    )


def read_commitment(commitment_id: str) -> dict:
    return get_success_data(api_client.get_commitment(commitment_id, CREDIT_OFFICER))


def read_investor(investor_id: str) -> dict:
    return get_success_data(api_client.get_investor(investor_id, CREDIT_OFFICER))


# ─── Advance booking, wire clearance and funding ──────────────────────────────

def book_advance(
    facility_id: str,
    custodian_id: str,
    investor_commitment_id: str = None,
    expected_facility_version: int = None,
    analyst_user_id: str = "ca_1",
    **overrides,
) -> dict:
    """`POST /advances` — creates the advance and mints the paired funding wire."""
    version = (
        expected_facility_version
        if expected_facility_version is not None
        else facility_version(facility_id)
    )
    return get_success_data(
        api_client.create_advance(
            advance_payload(
                facility_id,
                custodian_id,
                version,
                investor_commitment_id=investor_commitment_id,
                **overrides,
            ),
            make_collateral_analyst_headers(analyst_user_id),
        )
    )


def read_advance(advance_id: str) -> dict:
    return get_success_data(api_client.get_advance(advance_id, COLLATERAL_ANALYST))


def advance_version(advance_id: str) -> int:
    """The advance's current `version`, for the `expected_advance_version` token."""
    return read_advance(advance_id)["version"]


def wire_for_advance(advance_id: str) -> dict:
    """The advance's paired `WireInstruction`, newest last."""
    wires = get_success_data(
        api_client.list_advance_wire_instructions(advance_id, WIRE_OPERATOR)
    )
    assert wires, f"advance {advance_id} has no wire instruction"
    return wires[0]


def latest_wire_for_advance(advance_id: str) -> dict:
    wires = get_success_data(
        api_client.list_advance_wire_instructions(advance_id, WIRE_OPERATOR)
    )
    assert wires, f"advance {advance_id} has no wire instruction"
    return wires[-1]


def verify_wire(
    wire_id: str, callback_reference: str = "CB-301", operator_user_id: str = "wo_1"
) -> dict:
    """`POST /wire-instructions/{id}/decision` with `decision` of `VERIFY`."""
    return get_success_data(
        api_client.decide_wire_instruction(
            wire_id,
            wire_decision_payload("VERIFY", callback_reference=callback_reference),
            make_wire_operator_headers(operator_user_id),
        )
    )


def block_wire(
    wire_id: str, block_reason: str = None, operator_user_id: str = "wo_1"
) -> dict:
    """`POST /wire-instructions/{id}/decision` with `decision` of `BLOCK`."""
    payload = {"decision": "BLOCK"}
    if block_reason is not None:
        payload["block_reason"] = block_reason
    return get_success_data(
        api_client.decide_wire_instruction(
            wire_id, payload, make_wire_operator_headers(operator_user_id)
        )
    )


def fund_advance(advance_id: str, funder_user_id: str = "ca_1") -> dict:
    """`POST /advances/{id}/fund` — must be a different identity from the wire's decider."""
    return get_success_data(
        api_client.fund_advance(
            advance_id, make_collateral_analyst_headers(funder_user_id)
        )
    )


# ─── Custody receipts ─────────────────────────────────────────────────────────

def file_receipt(
    advance_id: str,
    custodian_id: str,
    exception_codes: list = None,
    document_types: list = None,
) -> dict:
    """`POST /advances/{id}/receipts` filed under the custodian's own identity."""
    payload = receipt_payload(custodian_id)
    if document_types is not None:
        payload["document_types"] = document_types
    if exception_codes is not None:
        payload["exception_codes"] = exception_codes
    return get_success_data(
        api_client.create_receipt(
            advance_id, payload, make_custodian_headers(custodian_id)
        )
    )


def cure_receipt(receipt_id: str, custodian_id: str, cured_exception_codes: list) -> dict:
    """`POST /receipts/{id}/cure` under the custodian's own identity."""
    return get_success_data(
        api_client.cure_receipt(
            receipt_id,
            receipt_cure_payload(cured_exception_codes),
            make_custodian_headers(custodian_id),
        )
    )


# ─── Valuation, shipment, settlement ──────────────────────────────────────────

def mark_to_market(advance_id: str, market_value_cents: int) -> dict:
    """`POST /advances/{id}/valuation` with a freshly read version token."""
    return get_success_data(
        api_client.value_advance(
            advance_id,
            valuation_payload(market_value_cents, advance_version(advance_id)),
            COLLATERAL_ANALYST,
        )
    )


def ship_advance(advance_id: str, investor_id: str) -> dict:
    """`POST /advances/{id}/ship` — issues the bailee letter."""
    return get_success_data(
        api_client.ship_advance(advance_id, ship_payload(investor_id), COLLATERAL_ANALYST)
    )


def purchase_advance(
    advance_id: str, investor_id: str, proceeds_reference: str = "WIRE-IN-20260806-01"
) -> dict:
    """`POST /advances/{id}/purchase` settled by the investor itself."""
    return get_success_data(
        api_client.purchase_advance(
            advance_id,
            make_investor_headers(investor_id),
            purchase_payload(proceeds_reference),
        )
    )


def repurchase_advance(advance_id: str, payment_amount_cents: int) -> dict:
    """`POST /advances/{id}/repurchase` at par outstanding."""
    return get_success_data(
        api_client.repurchase_advance(
            advance_id, repurchase_payload(payment_amount_cents), COLLATERAL_ANALYST
        )
    )


def raise_repurchase_demand(advance_id: str, reason: str = "DWELL_EXCEEDED") -> dict:
    return get_success_data(
        api_client.create_repurchase_demand(advance_id, {"reason": reason}, CREDIT_OFFICER)
    )


def escalate_repurchase_demand(demand_id: str) -> dict:
    return get_success_data(
        api_client.escalate_repurchase_demand(demand_id, CREDIT_OFFICER)
    )


# ─── Margin calls, cures and waivers ──────────────────────────────────────────

def raise_manual_margin_call(
    facility_id: str,
    trigger_reason: str = "COVENANT_BREACH",
    advance_id: str = None,
    cure_days: int = None,
    officer_user_id: str = "co_1",
) -> dict:
    """`POST /margin-calls` — a null `advance_id` means a facility-level call."""
    payload = margin_call_payload(facility_id, trigger_reason)
    if advance_id is not None:
        payload["advance_id"] = advance_id
    if cure_days is not None:
        payload["cure_days"] = cure_days
    return get_success_data(
        api_client.create_margin_call(payload, make_credit_officer_headers(officer_user_id))
    )


def facility_margin_calls(facility_id: str, params: dict = None) -> list:
    return get_success_data(
        api_client.list_facility_margin_calls(facility_id, CREDIT_OFFICER, params)
    )


def advance_margin_calls(advance_id: str, params: dict = None) -> list:
    return get_success_data(
        api_client.list_advance_margin_calls(advance_id, CREDIT_OFFICER, params)
    )


def first_open_margin_call(facility_id: str) -> dict:
    """The facility's earliest call still `ISSUED` or `PARTIALLY_CURED`."""
    for call in facility_margin_calls(facility_id):
        if call["status"] in ("ISSUED", "PARTIALLY_CURED"):
            return call
    raise AssertionError(f"facility {facility_id} has no open margin call")


def read_margin_call(margin_call_id: str) -> dict:
    return get_success_data(api_client.get_margin_call(margin_call_id, CREDIT_OFFICER))


def post_cure_payment(
    margin_call_id: str, facility_id: str, amount_cents: int
) -> dict:
    """`POST /margin-calls/{id}/cure-payments` posted by the `Borrower` itself."""
    version = read_margin_call(margin_call_id)["version"]
    return get_success_data(
        api_client.create_cure_payment(
            margin_call_id,
            cure_payment_payload(amount_cents, version),
            make_borrower_headers(facility_id),
        )
    )


def waive_margin_call(
    margin_call_id: str,
    reason: str = "Independent credit review cleared the exposure",
    officer_user_id: str = "co_2",
) -> dict:
    """`POST /margin-calls/{id}/waive` by an officer other than the issuer."""
    return get_success_data(
        api_client.waive_margin_call(
            margin_call_id, {"reason": reason}, make_credit_officer_headers(officer_user_id)
        )
    )


# ─── Covenant certification ───────────────────────────────────────────────────

def certify_covenants(facility_id: str, period_end: str, **overrides) -> dict:
    """`POST /facilities/{id}/covenant-tests`."""
    return get_success_data(
        api_client.create_covenant_test(
            facility_id, covenant_test_payload(period_end, **overrides), CREDIT_OFFICER
        )
    )


def waive_covenant_test(
    covenant_test_id: str, reason: str = "Sponsor support letter received"
) -> dict:
    return get_success_data(
        api_client.waive_covenant_test(
            covenant_test_id, {"reason": reason}, CREDIT_OFFICER
        )
    )


# ─── Aging run and ledger reads ───────────────────────────────────────────────

def run_aging(facility_id: str) -> dict:
    """`POST /facilities/{id}/aging-run` — the nightly batch."""
    return get_success_data(api_client.run_aging(facility_id, CREDIT_OFFICER))


def facility_ledger(facility_id: str, params: dict = None) -> list:
    return get_success_data(
        api_client.list_facility_ledger_entries(facility_id, CREDIT_OFFICER, params)
    )


def advance_ledger(advance_id: str, params: dict = None) -> list:
    return get_success_data(
        api_client.list_advance_ledger_entries(advance_id, CREDIT_OFFICER, params)
    )


def advance_bailee_letters(advance_id: str, params: dict = None) -> list:
    return get_success_data(
        api_client.list_advance_bailee_letters(advance_id, CREDIT_OFFICER, params)
    )


def advance_receipts(advance_id: str, params: dict = None) -> list:
    return get_success_data(
        api_client.list_advance_receipts(advance_id, CREDIT_OFFICER, params)
    )


# ══════════════════════════════════════════════════════════════════════════════
# Composite scenarios
# ══════════════════════════════════════════════════════════════════════════════

def setup_facility_panel(
    clock_utc: str = DEFAULT_CLOCK_UTC,
    facility_overrides: dict = None,
    rate_overrides: dict = None,
    extra_rate_rows: list = None,
    custodian_overrides: dict = None,
    investor_overrides: dict = None,
    commitment_overrides: dict = None,
    with_commitment: bool = True,
) -> Scenario:
    """`ACTIVE` facility + rate row + custodian + approved investor + commitment.

    Returns a Scenario with ``facility``, ``custodian``, ``investor``,
    ``commitment`` (may be ``None``) and ``facility_version_before_booking``.
    """
    facility = create_active_facility(
        clock_utc=clock_utc,
        facility_overrides=facility_overrides,
        rate_overrides=rate_overrides,
        extra_rate_rows=extra_rate_rows,
    )
    custodian = register_custodian(facility["id"], **(custodian_overrides or {}))
    investor = register_investor(facility["id"], **(investor_overrides or {}))
    commitment = None
    if with_commitment:
        commitment = record_commitment(
            facility["id"], investor["id"], **(commitment_overrides or {})
        )
    return Scenario(
        facility=facility,
        custodian=custodian,
        investor=investor,
        commitment=commitment,
        facility_version_before_booking=facility_version(facility["id"]),
        clock_utc=clock_utc,
    )


def setup_requested_advance(
    advance_overrides: dict = None, **panel_kwargs
) -> Scenario:
    """Panel + one booked advance and its `PENDING_VERIFICATION` wire."""
    scenario = setup_facility_panel(**panel_kwargs)
    advance = book_advance(
        scenario.facility["id"],
        scenario.custodian["id"],
        investor_commitment_id=(
            scenario.commitment["id"] if scenario.commitment else None
        ),
        expected_facility_version=scenario.facility_version_before_booking,
        **(advance_overrides or {}),
    )
    scenario.advance = advance
    scenario.wire = wire_for_advance(advance["id"])
    return scenario


def setup_advance_ready_to_fund(
    advance_overrides: dict = None,
    callback_reference: str = "CB-301",
    file_clear_receipt: bool = True,
    **panel_kwargs,
) -> Scenario:
    """Panel + booked advance + clear custodian receipt + `VERIFIED` wire."""
    scenario = setup_requested_advance(advance_overrides=advance_overrides, **panel_kwargs)
    if file_clear_receipt:
        scenario.receipt = file_receipt(
            scenario.advance["id"], scenario.custodian["id"]
        )
    scenario.wire = verify_wire(scenario.wire["id"], callback_reference)
    return scenario


def setup_funded_dry_advance(
    advance_overrides: dict = None, **panel_kwargs
) -> Scenario:
    """The canonical scenario: a DRY CONFORMING advance funded on the line.

    With the default 2,000,000,000 loan and a 0.98 advance rate the advance
    funds at 1,960,000,000.
    """
    scenario = setup_advance_ready_to_fund(
        advance_overrides=advance_overrides, **panel_kwargs
    )
    scenario.advance = fund_advance(scenario.advance["id"])
    return scenario


def setup_funded_wet_advance(
    advance_overrides: dict = None, **panel_kwargs
) -> Scenario:
    """A WET CONFORMING advance funded with the collateral file still outstanding.

    Wet funding is exempt from the receipt requirement, so no receipt is filed.
    With the default 2,000,000,000 loan, a 0.98 rate and a 0.02 wet haircut the
    advance funds at 1,920,000,000.
    """
    overrides = {"funding_type": "WET"}
    overrides.update(advance_overrides or {})
    scenario = setup_advance_ready_to_fund(
        advance_overrides=overrides, file_clear_receipt=False, **panel_kwargs
    )
    scenario.advance = fund_advance(scenario.advance["id"])
    return scenario


def setup_shipped_advance(
    ship_clock_utc: str = None, advance_overrides: dict = None, **panel_kwargs
) -> Scenario:
    """A funded DRY advance shipped under a fresh bailee letter."""
    scenario = setup_funded_dry_advance(
        advance_overrides=advance_overrides, **panel_kwargs
    )
    if ship_clock_utc:
        set_clock(ship_clock_utc)
    ship_advance(scenario.advance["id"], scenario.investor["id"])
    scenario.bailee_letter = advance_bailee_letters(scenario.advance["id"])[-1]
    scenario.advance = read_advance(scenario.advance["id"])
    return scenario


def setup_purchased_advance(
    ship_clock_utc: str = "2026-08-05T00:00:00Z",
    purchase_clock_utc: str = "2026-08-06T00:00:00Z",
    advance_overrides: dict = None,
    **panel_kwargs,
) -> Scenario:
    """A funded advance shipped and then settled by the take-out investor."""
    scenario = setup_shipped_advance(
        ship_clock_utc=ship_clock_utc, advance_overrides=advance_overrides, **panel_kwargs
    )
    if purchase_clock_utc:
        set_clock(purchase_clock_utc)
    purchase_advance(scenario.advance["id"], scenario.investor["id"])
    scenario.advance = read_advance(scenario.advance["id"])
    return scenario


def setup_advance_with_valuation_margin_call(
    market_value_cents: int = 1_900_000_000,
    advance_overrides: dict = None,
    **panel_kwargs,
) -> Scenario:
    """A funded DRY advance marked down far enough to issue a margin call.

    With the canonical 2,000,000,000 loan funded at 1,960,000,000, marking to
    1,900,000,000 leaves an eligible value of 1,862,000,000 and a required
    paydown of 98,000,000.
    """
    scenario = setup_funded_dry_advance(
        advance_overrides=advance_overrides, **panel_kwargs
    )
    scenario.advance = mark_to_market(scenario.advance["id"], market_value_cents)
    scenario.margin_call = first_open_margin_call(scenario.facility["id"])
    scenario.facility = read_facility(scenario.facility["id"])
    return scenario


def setup_manual_facility_margin_call(
    trigger_reason: str = "COVENANT_BREACH",
    officer_user_id: str = "co_1",
    advance_overrides: dict = None,
    **panel_kwargs,
) -> Scenario:
    """A funded DRY advance plus a hand-raised facility-level margin call.

    A facility-level call is sized at one tenth of `outstanding_principal_cents`,
    so 1,960,000,000 outstanding yields a 196,000,000 call.
    """
    scenario = setup_funded_dry_advance(
        advance_overrides=advance_overrides, **panel_kwargs
    )
    scenario.margin_call = raise_manual_margin_call(
        scenario.facility["id"],
        trigger_reason=trigger_reason,
        officer_user_id=officer_user_id,
    )
    scenario.facility = read_facility(scenario.facility["id"])
    return scenario


def setup_advance_with_exception_receipt(
    exception_codes: list = None,
    funding_type: str = "WET",
    advance_overrides: dict = None,
    **panel_kwargs,
) -> Scenario:
    """A funded advance whose collateral file arrived with document defects."""
    codes = exception_codes or ["MISSING_NOTE", "UNSIGNED_ASSIGNMENT"]
    if funding_type == "WET":
        scenario = setup_funded_wet_advance(
            advance_overrides=advance_overrides, **panel_kwargs
        )
    else:
        scenario = setup_funded_dry_advance(
            advance_overrides=advance_overrides, **panel_kwargs
        )
    scenario.receipt = file_receipt(
        scenario.advance["id"], scenario.custodian["id"], exception_codes=codes
    )
    scenario.advance = read_advance(scenario.advance["id"])
    scenario.facility = read_facility(scenario.facility["id"])
    return scenario


def setup_aged_advance(
    aged_clock_utc: str = "2026-09-05T00:00:00Z",
    advance_overrides: dict = None,
    **panel_kwargs,
) -> Scenario:
    """A funded DRY advance carried past its dwell limit, with one aging run.

    Records the run summary in ``aging_run`` and re-reads the advance and the
    facility afterwards.
    """
    scenario = setup_funded_dry_advance(
        advance_overrides=advance_overrides, **panel_kwargs
    )
    set_clock(aged_clock_utc)
    scenario.aging_run = run_aging(scenario.facility["id"])
    scenario.advance = read_advance(scenario.advance["id"])
    scenario.facility = read_facility(scenario.facility["id"])
    return scenario


def setup_suspended_facility_with_open_call(
    market_value_cents: int = 1_900_000_000, **panel_kwargs
) -> Scenario:
    """A `SUSPENDED` facility that still carries one open margin call.

    Reinstatement turns on the child call's state, not the facility row's.
    """
    scenario = setup_advance_with_valuation_margin_call(
        market_value_cents=market_value_cents, **panel_kwargs
    )
    scenario.facility = suspend_facility(scenario.facility["id"])
    return scenario


def setup_two_investor_panel(
    second_investor_overrides: dict = None,
    second_commitment_overrides: dict = None,
    **panel_kwargs,
) -> Scenario:
    """The canonical panel plus a second approved investor and its commitment."""
    scenario = setup_facility_panel(**panel_kwargs)
    defaults = {
        "investor_name": "Bravo Whole Loan Trust",
        "counterparty_rating": "B",
        "concentration_limit_pct": 0.60,
    }
    defaults.update(second_investor_overrides or {})
    scenario.second_investor = register_investor(scenario.facility["id"], **defaults)
    commitment_defaults = {
        "committed_amount_cents": 5_000_000_000,
        "effective_on": "2026-08-01",
        "expires_on": "2026-12-31",
    }
    commitment_defaults.update(second_commitment_overrides or {})
    scenario.second_commitment = record_commitment(
        scenario.facility["id"], scenario.second_investor["id"], **commitment_defaults
    )
    scenario.facility_version_before_booking = facility_version(scenario.facility["id"])
    return scenario


def book_and_fund_additional_advance(
    scenario: Scenario,
    investor_commitment_id: str = None,
    callback_reference: str = "CB-400",
    file_clear_receipt: bool = True,
    **advance_overrides,
) -> dict:
    """Book, receipt, wire-verify and fund one more advance on an existing panel."""
    advance = book_advance(
        scenario.facility["id"],
        scenario.custodian["id"],
        investor_commitment_id=investor_commitment_id,
        **advance_overrides,
    )
    if file_clear_receipt and advance_overrides.get("funding_type", "DRY") == "DRY":
        file_receipt(advance["id"], scenario.custodian["id"])
    wire = wire_for_advance(advance["id"])
    verify_wire(wire["id"], callback_reference)
    return fund_advance(advance["id"])


def book_advance_ready_to_fund(
    scenario: Scenario,
    investor_commitment_id: str = None,
    callback_reference: str = "CB-401",
    file_clear_receipt: bool = True,
    **advance_overrides,
) -> dict:
    """Book, receipt and wire-verify one more advance without funding it."""
    advance = book_advance(
        scenario.facility["id"],
        scenario.custodian["id"],
        investor_commitment_id=investor_commitment_id,
        **advance_overrides,
    )
    if file_clear_receipt and advance_overrides.get("funding_type", "DRY") == "DRY":
        file_receipt(advance["id"], scenario.custodian["id"])
    wire = wire_for_advance(advance["id"])
    verify_wire(wire["id"], callback_reference)
    return advance


#: The narrow rate row used by scenarios that need a par advance with no haircut.
PAR_RATE_ROW = {
    "product_code": "CONFORMING",
    "advance_rate": 1.0,
    "wet_funding_allowed": True,
    "wet_haircut": 0.0,
    "dwell_limit_days": 30,
    "aging_step_days": 15,
    "curtailment_step_rate": 0.005,
    "product_sublimit_cents": 5_000_000_000,
}

#: A small facility whose committed line is exactly one par advance wide.
SMALL_FACILITY = {
    "borrower_legal_name": "Narrow Line Mortgage Bankers LLC",
    "committed_amount_cents": 1_000_000_000,
    "wet_sublimit_cents": 1_000_000_000,
    "aged_sublimit_cents": 1_000_000_000,
    "scratch_and_dent_sublimit_cents": 500_000_000,
}


def setup_exhausted_facility() -> Scenario:
    """A facility funded to exactly zero `availability_cents`.

    The par rate row and the 1,000,000,000 committed line make the first
    advance consume the whole line, so priority 38's zero-headroom arm is
    reachable while the facility is otherwise healthy.
    """
    scenario = setup_facility_panel(
        facility_overrides=SMALL_FACILITY,
        rate_overrides=PAR_RATE_ROW,
        commitment_overrides={"committed_amount_cents": 5_000_000_000},
    )
    scenario.advance = book_advance(
        scenario.facility["id"],
        scenario.custodian["id"],
        investor_commitment_id=scenario.commitment["id"],
        expected_facility_version=scenario.facility_version_before_booking,
        loan_amount_cents=1_000_000_000,
    )
    file_receipt(scenario.advance["id"], scenario.custodian["id"])
    wire = wire_for_advance(scenario.advance["id"])
    verify_wire(wire["id"], "CB-500")
    scenario.advance = fund_advance(scenario.advance["id"])
    scenario.facility = read_facility(scenario.facility["id"])
    return scenario
