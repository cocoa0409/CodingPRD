"""Composite state builders.

Every builder drives the API through declared endpoints only, so each test starts
from an empty database and assembles exactly the world it needs. All builders take
**overrides so a test can move one literal without re-inventing the chain.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import (
    CLOCK_AFTER_RESPONSE_DUE,
    CLOCK_REGISTRY,
    CLOCK_TERM_START,
    SKU_ADJUSTMENT,
)
from .factories import (
    ADJUSTMENT_LINE,
    CA_RULE,
    DISPENSER_LINE,
    TX_RULE,
    complaint_payload,
    contract_usage_payload,
    line_item_payload,
    master_contract_payload,
    member_agency_payload,
    piggyback_analysis_payload,
    solicitation_payload,
    solicitation_response_payload,
    state_law_rule_payload,
    supplier_payload,
    usage_report_payload,
)
from .test_users import (
    ADMIN_INTAKE,
    ADMIN_PIGGYBACK,
    ADMIN_REVIEW,
    OFFICER_AWARDER,
    OFFICER_CONDUCTOR,
    make_member_headers,
    make_supplier_headers,
)


# ---------------------------------------------------------------------------
# Tier 0: single-step helpers
# ---------------------------------------------------------------------------
def set_clock(api, to_iso8601: str) -> dict:
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN_REVIEW))


def create_state_law_rule(api, **overrides) -> dict:
    return get_success_data(
        api.create_state_law_rule(state_law_rule_payload(**overrides), ADMIN_INTAKE)
    )


def seed_state_law_rules(api, rules=(TX_RULE, CA_RULE)) -> dict:
    """Register one configuration row per supplied specification, keyed by state code."""
    seeded = {}
    for rule in rules:
        row = create_state_law_rule(api, **rule)
        seeded[row["state_code"]] = row
    return seeded


def register_supplier(api, **overrides) -> dict:
    return get_success_data(api.create_supplier(supplier_payload(**overrides), ADMIN_INTAKE))


def qualify_supplier(api, supplier_id) -> dict:
    return get_success_data(
        api.supplier_qualification(supplier_id, {"action": "QUALIFY"}, ADMIN_REVIEW)
    )


def register_qualified_supplier(api, **overrides) -> dict:
    supplier = register_supplier(api, **overrides)
    return qualify_supplier(api, supplier["id"])


def create_member(api, **overrides) -> dict:
    return get_success_data(
        api.create_member_agency(member_agency_payload(**overrides), ADMIN_INTAKE)
    )


def verify_member(api, member_id, **payload_extras) -> dict:
    payload = {"action": "VERIFY"}
    payload.update(payload_extras)
    return get_success_data(api.member_registration(member_id, payload, ADMIN_REVIEW))


def setup_active_member(api, **overrides) -> dict:
    """Register a member agency and carry it through eligibility verification."""
    member = create_member(api, **overrides)
    return verify_member(api, member["id"])


def read_member(api, member_id) -> dict:
    return get_success_data(api.get_member_agency(member_id, ADMIN_REVIEW))


def read_contract(api, contract_id) -> dict:
    return get_success_data(api.get_master_contract(contract_id, ADMIN_REVIEW))


def read_supplier(api, supplier_id) -> dict:
    return get_success_data(api.get_supplier(supplier_id, ADMIN_REVIEW))


def read_usage(api, usage_id) -> dict:
    return get_success_data(api.get_contract_usage(usage_id, ADMIN_REVIEW))


def read_report(api, report_id) -> dict:
    return get_success_data(api.get_usage_report(report_id, ADMIN_REVIEW))


def read_analysis(api, analysis_id) -> dict:
    return get_success_data(api.get_piggyback_analysis(analysis_id, ADMIN_REVIEW))


def read_line_item(api, line_item_id) -> dict:
    return get_success_data(api.get_contract_line_item(line_item_id, ADMIN_REVIEW))


def read_solicitation(api, solicitation_id) -> dict:
    return get_success_data(api.get_solicitation(solicitation_id, ADMIN_REVIEW))


def read_amendment(api, amendment_id) -> dict:
    return get_success_data(api.get_contract_amendment(amendment_id, ADMIN_REVIEW))


def read_complaint(api, complaint_id) -> dict:
    return get_success_data(api.get_complaint(complaint_id, ADMIN_REVIEW))


def read_response(api, response_id) -> dict:
    return get_success_data(api.get_solicitation_response(response_id, ADMIN_REVIEW))


# ---------------------------------------------------------------------------
# Tier 1: state progression of the competitive process
# ---------------------------------------------------------------------------
def setup_posted_solicitation(api, *, rules=(TX_RULE, CA_RULE), clock=CLOCK_REGISTRY, **overrides):
    """Seed configuration, qualify two suppliers, and post one solicitation."""
    set_clock(api, clock)
    seeded = seed_state_law_rules(api, rules)
    # Supplier qualification resolves the supplier's home_state_code against the
    # configuration registry, so both suppliers must sit in a configured state.
    state_a = "TX" if "TX" in seeded else next(iter(seeded))
    state_b = "CA" if "CA" in seeded else state_a
    supplier_a = register_qualified_supplier(api, legal_name="Acme Facility Supply LLC",
                                             home_state_code=state_a)
    supplier_b = register_qualified_supplier(api, legal_name="Bright Path Janitorial Inc",
                                             home_state_code=state_b)
    solicitation = get_success_data(
        api.create_solicitation(solicitation_payload(**overrides), OFFICER_CONDUCTOR)
    )
    solicitation = get_success_data(
        api.solicitation_lifecycle(solicitation["id"], {"action": "POST_NOTICE"}, OFFICER_CONDUCTOR)
    )
    return {
        "rules": seeded,
        "supplier_a": supplier_a,
        "supplier_b": supplier_b,
        "solicitation": solicitation,
    }


def file_response(api, solicitation_id, supplier, **overrides) -> dict:
    return get_success_data(
        api.create_solicitation_response(
            solicitation_response_payload(solicitation_id, supplier["id"], **overrides),
            make_supplier_headers(supplier["id"]),
        )
    )


def setup_evaluated_solicitation(api, *, world=None, value_a=1000000, value_b=1250000, **overrides):
    """Two live responses on a solicitation whose response window has closed."""
    world = world or setup_posted_solicitation(api, **overrides)
    sol_id = world["solicitation"]["id"]
    world["response_a"] = file_response(
        api, sol_id, world["supplier_a"], proposed_annual_value_cents=value_a
    )
    world["response_b"] = file_response(
        api, sol_id, world["supplier_b"], proposed_annual_value_cents=value_b
    )
    set_clock(api, CLOCK_AFTER_RESPONSE_DUE)
    world["solicitation"] = get_success_data(
        api.solicitation_lifecycle(sol_id, {"action": "OPEN_EVALUATION"}, OFFICER_CONDUCTOR)
    )
    return world


def setup_awarded_solicitation(api, *, world=None, technical_a=88.00, technical_b=95.00, **overrides):
    """Carry the competitive dimension all the way to AWARDED with two scored responses."""
    world = world or setup_evaluated_solicitation(api, **overrides)
    sol_id = world["solicitation"]["id"]
    world["response_a"] = get_success_data(
        api.response_review(
            world["response_a"]["id"],
            {"action": "MARK_RESPONSIVE", "technical_score": technical_a},
            OFFICER_CONDUCTOR,
        )
    )
    world["response_b"] = get_success_data(
        api.response_review(
            world["response_b"]["id"],
            {"action": "MARK_RESPONSIVE", "technical_score": technical_b},
            OFFICER_CONDUCTOR,
        )
    )
    get_success_data(
        api.solicitation_lifecycle(sol_id, {"action": "RECOMMEND_AWARD"}, OFFICER_CONDUCTOR)
    )
    world["solicitation"] = get_success_data(
        api.solicitation_lifecycle(sol_id, {"action": "AWARD"}, OFFICER_AWARDER)
    )
    return world


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — contract, price sheet, membership
# ---------------------------------------------------------------------------
def add_line_item(api, contract_id, spec=None, **overrides) -> dict:
    payload = line_item_payload(**{**(spec or {}), **overrides})
    return get_success_data(api.create_line_item(contract_id, payload, OFFICER_AWARDER))


def setup_pending_contract(api, *, world=None, lines=(DISPENSER_LINE,), **overrides):
    """Award a master contract and publish its price-sheet lines, still PENDING_EXECUTION."""
    contract_overrides = overrides.pop("contract_overrides", {})
    world = world or setup_awarded_solicitation(api, **overrides)
    world["contract"] = get_success_data(
        api.create_master_contract(
            master_contract_payload(
                world["solicitation"]["id"], world["supplier_a"]["id"], **contract_overrides
            ),
            OFFICER_AWARDER,
        )
    )
    world["lines"] = {}
    for spec in lines:
        row = add_line_item(api, world["contract"]["id"], spec)
        world["lines"][row["sku"]] = row
    return world


def setup_active_contract(api, *, world=None, lines=(DISPENSER_LINE,), clock=CLOCK_TERM_START,
                          **overrides):
    """A fully executed master contract sitting ACTIVE with a live price sheet."""
    world = setup_pending_contract(api, world=world, lines=lines, **overrides)
    set_clock(api, clock)
    world["contract"] = get_success_data(
        api.contract_award_status(world["contract"]["id"], {"action": "EXECUTE"}, ADMIN_REVIEW)
    )
    for sku in list(world["lines"]):
        world["lines"][sku] = read_line_item(api, world["lines"][sku]["id"])
    return world


def open_analysis(api, member_id, contract_id, *, expected_version=None, headers=ADMIN_PIGGYBACK,
                 **overrides) -> dict:
    """Open an authority analysis, pinning the member version the caller last read."""
    if expected_version is None:
        expected_version = read_member(api, member_id)["version"]
    return get_success_data(
        api.create_piggyback_analysis(
            piggyback_analysis_payload(member_id, contract_id, expected_version, **overrides),
            headers,
        )
    )


def determine_analysis(api, analysis_id, **payload_extras) -> dict:
    payload = {"action": "DETERMINE"}
    payload.update(payload_extras)
    return get_success_data(api.analysis_determination(analysis_id, payload, ADMIN_PIGGYBACK))


def setup_determined_analysis(api, member_id, contract_id, *, waiver_reference=None,
                              **overrides) -> dict:
    """Open and determine one authority opinion for a member-and-contract pair."""
    create_extras = {}
    if waiver_reference is not None:
        create_extras["waiver_reference"] = waiver_reference
    analysis = open_analysis(api, member_id, contract_id, **create_extras, **overrides)
    return determine_analysis(api, analysis["id"])


def setup_authorised_member(api, world, **member_overrides):
    """An ACTIVE member with a determined authority opinion on the world's contract."""
    member = setup_active_member(api, **member_overrides)
    analysis = setup_determined_analysis(api, member["id"], world["contract"]["id"])
    return member, analysis


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts for orders and periods
# ---------------------------------------------------------------------------
def record_usage(api, contract_id, member_id, line_item_id, analysis_id, **overrides) -> dict:
    return get_success_data(
        api.create_contract_usage(
            contract_usage_payload(contract_id, member_id, line_item_id, analysis_id, **overrides),
            make_member_headers(member_id),
        )
    )


def confirm_usage(api, usage) -> dict:
    return get_success_data(
        api.usage_disposition(
            usage["id"], {"action": "CONFIRM"}, make_member_headers(usage["member_agency_id"])
        )
    )


def retract_usage(api, usage) -> dict:
    return get_success_data(
        api.usage_disposition(
            usage["id"], {"action": "RETRACT"}, make_member_headers(usage["member_agency_id"])
        )
    )


def record_confirmed_usage(api, contract_id, member_id, line_item_id, analysis_id, **overrides):
    usage = record_usage(api, contract_id, member_id, line_item_id, analysis_id, **overrides)
    return confirm_usage(api, usage)


# ---------------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting
# ---------------------------------------------------------------------------
def prime_committed_spend(api, world, member, analysis, quantity, *, confirm=False) -> dict:
    """Move a member's committed spend onto an exact figure using the one-cent line.

    The one-cent catalogue line prices at exactly one cent per unit under every
    discount tier, so a quantity of N lands a chargeable base of N cents and the
    order total is N plus the administrative fee assessed on it.
    """
    line = world["lines"][SKU_ADJUSTMENT]
    usage = record_usage(
        api, world["contract"]["id"], member["id"], line["id"], analysis["id"], quantity=quantity
    )
    if confirm:
        usage = confirm_usage(api, usage)
    return usage


# ---------------------------------------------------------------------------
# Tier 5: period reporting, remittance and finalisation
# ---------------------------------------------------------------------------
def open_report(api, world, **overrides) -> dict:
    supplier_id = world["contract"]["supplier_id"]
    return get_success_data(
        api.create_usage_report(
            usage_report_payload(world["contract"]["id"], **overrides),
            make_supplier_headers(supplier_id),
        )
    )


def submit_report(api, world, report_id) -> dict:
    supplier_id = world["contract"]["supplier_id"]
    return get_success_data(
        api.report_submission(
            report_id, {"action": "SUBMIT"}, make_supplier_headers(supplier_id)
        )
    )


def accept_report(api, report_id) -> dict:
    return get_success_data(api.report_review(report_id, {"action": "ACCEPT"}, ADMIN_REVIEW))


def reconcile_report(api, report_id) -> dict:
    return get_success_data(api.report_review(report_id, {"action": "RECONCILE"}, ADMIN_REVIEW))


def remit_fee(api, world, report_id, amount_cents) -> dict:
    supplier_id = world["contract"]["supplier_id"]
    return get_success_data(
        api.report_fee_remittance(
            report_id,
            {"action": "REMIT", "amount_cents": amount_cents},
            make_supplier_headers(supplier_id),
        )
    )


def run_compliance_sweep(api, contract_id, **payload_extras) -> dict:
    payload = dict(payload_extras)
    return get_success_data(api.contract_compliance_sweep(contract_id, payload, ADMIN_REVIEW))


# ---------------------------------------------------------------------------
# Complaint lifecycle shortcuts
# ---------------------------------------------------------------------------
def file_complaint(api, contract_id, member_id, **overrides) -> dict:
    return get_success_data(
        api.create_complaint(
            complaint_payload(contract_id, member_id, **overrides), make_member_headers(member_id)
        )
    )


def open_investigation(api, complaint_id, headers) -> dict:
    return get_success_data(
        api.complaint_investigation(complaint_id, {"action": "OPEN_INVESTIGATION"}, headers)
    )


def substantiate_complaint(api, complaint_id, headers) -> dict:
    return get_success_data(
        api.complaint_decision(complaint_id, {"action": "SUBSTANTIATE"}, headers)
    )


def setup_substantiated_complaint(api, contract_id, member_id, *, severity="MAJOR",
                                  investigator, adjudicator, **overrides) -> dict:
    """File a complaint and carry it through investigation to substantiation."""
    complaint = file_complaint(api, contract_id, member_id, severity=severity, **overrides)
    open_investigation(api, complaint["id"], investigator)
    return substantiate_complaint(api, complaint["id"], adjudicator)


# ---------------------------------------------------------------------------
# Whole-world shortcut used by the fee-settlement and cascade scenarios
# ---------------------------------------------------------------------------
def setup_confirmed_usage_world(api, *, quantity_each=1, order_count=3, line=None, **overrides):
    """An ACTIVE contract, an authorised member, and N confirmed orders on one line.

    The contract carries the liner, dispenser, cart and one-cent adjustment lines so
    a single world can serve pricing, sweep and ledger scenarios.
    """
    from .factories import CART_LINE, LINER_LINE

    world = setup_active_contract(
        api, lines=(LINER_LINE, DISPENSER_LINE, CART_LINE, ADJUSTMENT_LINE), **overrides
    )
    member, analysis = setup_authorised_member(api, world)
    world["member"] = member
    world["analysis"] = analysis
    target = line or LINER_LINE["sku"]
    world["usages"] = [
        record_confirmed_usage(
            api,
            world["contract"]["id"],
            member["id"],
            world["lines"][target]["id"],
            analysis["id"],
            quantity=quantity_each,
        )
        for _ in range(order_count)
    ]
    return world
