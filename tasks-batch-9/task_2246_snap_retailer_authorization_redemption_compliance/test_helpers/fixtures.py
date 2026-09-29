"""Composite preconditions.

The harness restarts the API before every test, so each test starts against an
empty database and builds everything it needs from scratch through the public
endpoints. The helpers below are the anchored chains the design indices reuse:
the authorized-store chain, the four-closed-period redemption history, the
depot/terminal/deployment chain and the sanction-case ladder.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import validate_paginated, validate_success

from .api_client import api_client
from .constants import AUG_01
from . import factories as f
from .test_users import (
    ADMIN_ALT_USER_ID,
    ADMIN_USER_ID,
    ANALYST_ALT_USER_ID,
    ANALYST_USER_ID,
    REVIEW_OFFICER_ALT_USER_ID,
    REVIEW_OFFICER_USER_ID,
    make_admin_review_officer_headers,
    make_anonymous_headers,
    make_fns_admin_headers,
    make_fns_analyst_headers,
    make_inspector_headers,
    make_retailer_owner_headers,
    make_store_clerk_headers,
)

# --------------------------------------------------------------------------
# Headers for the four roles whose X-User-ID is an opaque string
# --------------------------------------------------------------------------

ANON = make_anonymous_headers()
ADMIN = make_fns_admin_headers(ADMIN_USER_ID)
ADMIN_ALT = make_fns_admin_headers(ADMIN_ALT_USER_ID)
ANALYST = make_fns_analyst_headers(ANALYST_USER_ID)
ANALYST_ALT = make_fns_analyst_headers(ANALYST_ALT_USER_ID)
REVIEWER = make_admin_review_officer_headers(REVIEW_OFFICER_USER_ID)
REVIEWER_ALT = make_admin_review_officer_headers(REVIEW_OFFICER_ALT_USER_ID)


def created(response: Any) -> Dict[str, Any]:
    """A creation returns HTTP 201 with the created resource in `data`."""
    return validate_success(response, 201)


def ok(response: Any) -> Dict[str, Any]:
    """Every other successful operation, including every read, returns 200."""
    return validate_success(response, 200)


def rows(response: Any) -> List[Dict[str, Any]]:
    """A list response carries the rows in `data` and the counts in `meta`."""
    data, _meta = validate_paginated(response)
    return data


def advance_clock(instant: str) -> None:
    """Only an FnsAdmin may move the logical clock."""
    ok(api_client.set_clock(f.clock_payload(instant), ADMIN))


# --------------------------------------------------------------------------
# The staple inventory anchors the design indices reuse
# --------------------------------------------------------------------------

# Twelve varieties across four categories, every one of them stocked at least
# three deep, perishables in three categories: qualifies under both the desk
# variant and the on-site variant.
INV_PASS: List[Dict[str, Any]] = [
    f.inventory_line("BREAD_CEREAL", "RICE", 4, False),
    f.inventory_line("BREAD_CEREAL", "OATS", 3, False),
    f.inventory_line("BREAD_CEREAL", "TORTILLA", 5, False),
    f.inventory_line("DAIRY", "MILK", 6, True),
    f.inventory_line("DAIRY", "CHEESE", 4, True),
    f.inventory_line("DAIRY", "YOGURT", 3, True),
    f.inventory_line("FRUIT_VEG", "APPLE", 5, True),
    f.inventory_line("FRUIT_VEG", "ONION", 4, True),
    f.inventory_line("FRUIT_VEG", "CANNED_CORN", 3, False),
    f.inventory_line("MEAT_POULTRY_FISH", "CHICKEN", 3, True),
    f.inventory_line("MEAT_POULTRY_FISH", "TUNA_CAN", 4, False),
    f.inventory_line("MEAT_POULTRY_FISH", "GROUND_BEEF", 3, True),
]

# Fourteen varieties: fruit and vegetables holds five varieties of two units,
# which is broad enough for the desk variant and too shallow for the on-site
# variant, so the identical list diverges between the two.
INV_DIVERGENT: List[Dict[str, Any]] = [
    f.inventory_line("BREAD_CEREAL", "RICE", 3, False),
    f.inventory_line("BREAD_CEREAL", "OATS", 3, False),
    f.inventory_line("BREAD_CEREAL", "TORTILLA", 3, False),
    f.inventory_line("DAIRY", "MILK", 3, True),
    f.inventory_line("DAIRY", "CHEESE", 3, True),
    f.inventory_line("DAIRY", "YOGURT", 3, True),
    f.inventory_line("FRUIT_VEG", "APPLE", 2, True),
    f.inventory_line("FRUIT_VEG", "ONION", 2, True),
    f.inventory_line("FRUIT_VEG", "CANNED_CORN", 2, False),
    f.inventory_line("FRUIT_VEG", "POTATO", 2, True),
    f.inventory_line("FRUIT_VEG", "CARROT", 2, True),
    f.inventory_line("MEAT_POULTRY_FISH", "CHICKEN", 3, True),
    f.inventory_line("MEAT_POULTRY_FISH", "TUNA_CAN", 3, False),
    f.inventory_line("MEAT_POULTRY_FISH", "GROUND_BEEF", 3, True),
]

# --------------------------------------------------------------------------
# Basket anchors
# --------------------------------------------------------------------------

BASKET_SIMPLE: List[Dict[str, Any]] = [
    f.line_item("MILK-1G", "STAPLE_FOOD", 379, 2),
]

# Three eligible lines totalling 1,296c and three ineligible lines totalling
# 2,597c.
BASKET_SPLIT: List[Dict[str, Any]] = [
    f.line_item("MILK-1G", "STAPLE_FOOD", 379, 2),
    f.line_item("BREAD-WW", "STAPLE_FOOD", 289, 1),
    f.line_item("SEEDS-TOM", "SEED_PLANT", 249, 1),
    f.line_item("BEER-6PK", "ALCOHOL", 999, 1),
    f.line_item("HOTDELI", "HOT_PREPARED", 599, 1),
    f.line_item("PAPERTWL", "NONFOOD", 333, 3),
]


# --------------------------------------------------------------------------
# Owners and stores
# --------------------------------------------------------------------------

def create_owner(**overrides: Any) -> Dict[str, Any]:
    """Owner registration is the one route an anonymous caller may use."""
    return created(api_client.create_owner(f.owner_payload(**overrides), ANON))


def owner_headers(owner: Dict[str, Any]) -> Dict[str, str]:
    return make_retailer_owner_headers(owner["id"])


def create_store(owner: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    return created(
        api_client.create_store(f.store_payload(owner["id"], **overrides), ADMIN)
    )


def clerk_headers(store: Dict[str, Any]) -> Dict[str, str]:
    return make_store_clerk_headers(store["id"])


def refresh_store(store_id: str) -> Dict[str, Any]:
    return ok(api_client.get_store(store_id, ADMIN))


def refresh_owner(owner_id: str) -> Dict[str, Any]:
    return ok(api_client.get_owner(owner_id, ADMIN))


def refresh_application(application_id: str) -> Dict[str, Any]:
    return ok(api_client.get_application(application_id, ADMIN))


def refresh_inspector(inspector_id: str) -> Dict[str, Any]:
    return ok(api_client.get_inspector(inspector_id, ADMIN))


def refresh_visit(visit_id: str) -> Dict[str, Any]:
    return ok(api_client.get_store_visit(visit_id, ADMIN))


def refresh_period(period_id: str) -> Dict[str, Any]:
    return ok(api_client.get_redemption_period(period_id, ANALYST))


def refresh_investigation(investigation_id: str) -> Dict[str, Any]:
    return ok(api_client.get_investigation(investigation_id, ANALYST))


def refresh_case(case_id: str) -> Dict[str, Any]:
    return ok(api_client.get_sanction_case(case_id, ADMIN))


def refresh_depot(depot_id: str) -> Dict[str, Any]:
    return ok(api_client.get_equipment_depot(depot_id, ADMIN))


def refresh_terminal(terminal_id: str) -> Dict[str, Any]:
    return ok(api_client.get_ebt_terminal(terminal_id, ADMIN))


def refresh_deployment(deployment_id: str) -> Dict[str, Any]:
    return ok(api_client.get_terminal_deployment(deployment_id, ADMIN))


def refresh_order(order_id: str) -> Dict[str, Any]:
    return ok(api_client.get_equipment_order(order_id, ADMIN))


def refresh_transaction(transaction_id: str) -> Dict[str, Any]:
    return ok(api_client.get_pos_transaction(transaction_id, ADMIN))


# --------------------------------------------------------------------------
# Inspectors
# --------------------------------------------------------------------------

def create_inspector(**overrides: Any) -> Dict[str, Any]:
    return created(api_client.create_inspector(f.inspector_payload(**overrides), ADMIN))


def inspector_headers(inspector: Dict[str, Any]) -> Dict[str, str]:
    return make_inspector_headers(inspector["id"])


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------

def create_application(
    owner: Dict[str, Any],
    store: Dict[str, Any],
    inventory_lines: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.application_payload(
        store["id"],
        store["version"],
        reported_inventory_lines=INV_PASS if inventory_lines is None else inventory_lines,
        **overrides,
    )
    return created(api_client.create_application(payload, owner_headers(owner)))


def submit_application(
    application: Dict[str, Any], owner: Dict[str, Any]
) -> Dict[str, Any]:
    return ok(api_client.submit_application(application["id"], owner_headers(owner)))


def schedule_visit(
    application: Dict[str, Any], inspector: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    payload = f.store_visit_payload(application["id"], inspector["id"], **overrides)
    return created(api_client.create_store_visit(payload, ANALYST))


def start_visit(visit: Dict[str, Any], inspector: Dict[str, Any]) -> Dict[str, Any]:
    return ok(api_client.start_store_visit(visit["id"], inspector_headers(inspector)))


def submit_findings(
    visit: Dict[str, Any],
    inspector: Dict[str, Any],
    observed_inventory_lines: Optional[List[Dict[str, Any]]] = None,
    observed_staple_shelf_linear_feet: int = 30,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.findings_payload(
        observed_staple_shelf_linear_feet=observed_staple_shelf_linear_feet,
        observed_inventory_lines=(
            INV_PASS if observed_inventory_lines is None else observed_inventory_lines
        ),
        **overrides,
    )
    return ok(api_client.submit_findings(visit["id"], payload, inspector_headers(inspector)))


def decide_application(
    application: Dict[str, Any], outcome: str = "APPROVED", **overrides: Any
) -> Dict[str, Any]:
    return ok(
        api_client.decide_application(
            application["id"], f.decision_payload(outcome, **overrides), ADMIN
        )
    )


# --------------------------------------------------------------------------
# The authorized-store chain
# --------------------------------------------------------------------------

@dataclass
class AuthorizedStore:
    """Owner, store, application, inspector and pre-authorization visit, walked
    all the way to an APPROVED decision on the default clock."""

    owner: Dict[str, Any]
    store: Dict[str, Any]
    application: Dict[str, Any]
    inspector: Dict[str, Any]
    visit: Dict[str, Any]

    @property
    def owner_id(self) -> str:
        return self.owner["id"]

    @property
    def store_id(self) -> str:
        return self.store["id"]

    @property
    def application_id(self) -> str:
        return self.application["id"]

    @property
    def inspector_id(self) -> str:
        return self.inspector["id"]

    @property
    def visit_id(self) -> str:
        return self.visit["id"]

    @property
    def owner_h(self) -> Dict[str, str]:
        return make_retailer_owner_headers(self.owner["id"])

    @property
    def clerk_h(self) -> Dict[str, str]:
        return make_store_clerk_headers(self.store["id"])

    @property
    def inspector_h(self) -> Dict[str, str]:
        return make_inspector_headers(self.inspector["id"])


def authorized_store(
    store_overrides: Optional[Dict[str, Any]] = None,
    inventory_lines: Optional[List[Dict[str, Any]]] = None,
) -> AuthorizedStore:
    """Empty database to an AUTHORIZED store: register the owner, create the
    store, file and submit a CRITERION_A application, hire an inspector, schedule
    and start the 00:00-02:00 pre-authorization visit, file passing findings and
    approve."""
    owner = create_owner()
    store = create_store(owner, **(store_overrides or {}))
    application = create_application(owner, store, inventory_lines=inventory_lines)
    submit_application(application, owner)
    inspector = create_inspector()
    visit = schedule_visit(application, inspector)
    start_visit(visit, inspector)
    submit_findings(
        visit,
        inspector,
        observed_inventory_lines=INV_PASS if inventory_lines is None else inventory_lines,
    )
    decide_application(application)
    return AuthorizedStore(
        owner=refresh_owner(owner["id"]),
        store=refresh_store(store["id"]),
        application=refresh_application(application["id"]),
        inspector=refresh_inspector(inspector["id"]),
        visit=refresh_visit(visit["id"]),
    )


def pending_visit_application(
    inventory_lines: Optional[List[Dict[str, Any]]] = None,
) -> AuthorizedStore:
    """The same chain stopped just after the visit is started, so the next call
    can be the findings submission that decides the eligibility variants."""
    owner = create_owner()
    store = create_store(owner)
    application = create_application(owner, store, inventory_lines=inventory_lines)
    submit_application(application, owner)
    inspector = create_inspector()
    visit = schedule_visit(application, inspector)
    start_visit(visit, inspector)
    return AuthorizedStore(
        owner=owner,
        store=refresh_store(store["id"]),
        application=refresh_application(application["id"]),
        inspector=refresh_inspector(inspector["id"]),
        visit=refresh_visit(visit["id"]),
    )


# --------------------------------------------------------------------------
# Redemption monitoring history
# --------------------------------------------------------------------------

def create_period(store_id: str, **overrides: Any) -> Dict[str, Any]:
    return created(
        api_client.create_redemption_period(
            f.redemption_period_payload(store_id, **overrides), ANALYST
        )
    )


def import_settlement(period_id: str, **overrides: Any) -> Dict[str, Any]:
    return ok(
        api_client.import_settlement(period_id, f.settlement_payload(**overrides), ANALYST)
    )


def close_period(period_id: str) -> Dict[str, Any]:
    return ok(api_client.close_redemption_period(period_id, ANALYST))


# The four settled months every civil-money-penalty chain averages over:
# 1,234,567c, 1,000,000c, 900,000c and 2,000,000c, none of which scores above
# FLAG_L1.
CLOSED_PERIOD_SPECS = (
    (1, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", 1234567, 40),
    (2, "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z", 1000000, 30),
    (3, "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z", 900000, 28),
    (4, "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", 2000000, 50),
)


def four_closed_periods(store_id: str) -> List[Dict[str, Any]]:
    """Four CLOSED periods in index order, each one's aggregates supplied by a
    settlement import and then frozen by the close."""
    periods: List[Dict[str, Any]] = []
    for index, start, end, total, count in CLOSED_PERIOD_SPECS:
        period = create_period(
            store_id, period_index=index, period_start=start, period_end=end
        )
        import_settlement(
            period["id"], imported_total_cents=total, imported_transaction_count=count
        )
        periods.append(close_period(period["id"]))
    return periods


# The settlement profile that scores 92 and lands on FLAG_L3 for a CONVENIENCE
# store whose size expectation is 1,250,000c.
FLAG_L3_IMPORT = {
    "imported_total_cents": 4375000,
    "imported_transaction_count": 25,
    "imported_large_transaction_cents": 2625000,
    "imported_even_dollar_transaction_count": 6,
}


def open_flagged_period(store_id: str, **overrides: Any) -> Dict[str, Any]:
    """An OPEN 2026-06 period already carrying the FLAG_L3 settlement profile, so
    the next call can be the close whose cascade is under test."""
    period = create_period(
        store_id,
        period_index=1,
        period_start="2026-06-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
        **overrides,
    )
    import_settlement(period["id"], **FLAG_L3_IMPORT)
    return period


# --------------------------------------------------------------------------
# Equipment: depot, terminal, deployment
# --------------------------------------------------------------------------

def create_depot(**overrides: Any) -> Dict[str, Any]:
    return created(api_client.create_equipment_depot(f.depot_payload(**overrides), ADMIN))


def create_terminal(depot: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    return created(
        api_client.create_ebt_terminal(f.terminal_payload(depot["id"], **overrides), ADMIN)
    )


def create_deployment(
    store: Dict[str, Any], terminal: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    payload = f.deployment_payload(store["id"], terminal["id"], **overrides)
    return created(api_client.create_terminal_deployment(payload, ADMIN))


def activate_deployment(deployment: Dict[str, Any]) -> Dict[str, Any]:
    return ok(api_client.activate_deployment(deployment["id"], ADMIN))


@dataclass
class Equipment:
    depot: Dict[str, Any]
    terminal: Dict[str, Any]
    deployment: Dict[str, Any]

    @property
    def depot_id(self) -> str:
        return self.depot["id"]

    @property
    def terminal_id(self) -> str:
        return self.terminal["id"]

    @property
    def deployment_id(self) -> str:
        return self.deployment["id"]


def reserved_equipment(
    store: Dict[str, Any], total_units_owned: int = 5, **deployment_overrides: Any
) -> Equipment:
    """A five-unit TX depot, terminal EBT-0001 and a RESERVED deployment covering
    2026-08-01 through 2027-07-31."""
    depot = create_depot(total_units_owned=total_units_owned)
    terminal = create_terminal(depot)
    deployment = create_deployment(
        store,
        terminal,
        deploy_start=AUG_01,
        deploy_end="2027-07-31T00:00:00Z",
        **deployment_overrides,
    )
    return Equipment(depot=depot, terminal=terminal, deployment=deployment)


def active_equipment(
    store: Dict[str, Any], total_units_owned: int = 5, **deployment_overrides: Any
) -> Equipment:
    """The same chain with the deployment activated, which is what a point-of-sale
    transaction needs."""
    equipment = reserved_equipment(store, total_units_owned, **deployment_overrides)
    equipment.deployment = activate_deployment(equipment.deployment)
    return equipment


# --------------------------------------------------------------------------
# Investigations
# --------------------------------------------------------------------------

def open_investigation(store_id: str, **overrides: Any) -> Dict[str, Any]:
    return created(
        api_client.create_investigation(f.investigation_payload(store_id, **overrides), ANALYST)
    )


def add_evidence(investigation_id: str, **overrides: Any) -> Dict[str, Any]:
    return ok(
        api_client.add_evidence(investigation_id, f.evidence_payload(**overrides), ANALYST)
    )


def conclude_investigation(
    investigation_id: str, substantiated_violation: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """A different analyst from the one who opened the investigation must
    conclude it."""
    return ok(
        api_client.conclude_investigation(
            investigation_id,
            f.conclude_payload(substantiated_violation),
            headers or ANALYST_ALT,
        )
    )


def substantiated_ineligible_investigation(store_id: str) -> Dict[str, Any]:
    """A tip-opened investigation carrying one household interview, concluded
    SUBSTANTIATED for ineligible item sales."""
    investigation = open_investigation(store_id, opened_reason="TIP")
    add_evidence(
        investigation["id"],
        evidence_type="HOUSEHOLD_INTERVIEW",
        observed_at="2026-07-15T00:00:00Z",
    )
    return conclude_investigation(investigation["id"], "INELIGIBLE_ITEM_SALES")


def substantiated_trafficking_investigation(store_id: str) -> Dict[str, Any]:
    """A tip-opened investigation carrying a fresh undercover buy and a fresh
    EBT-only pattern, which together score exactly 60 and clear the trafficking
    floor."""
    investigation = open_investigation(store_id, opened_reason="TIP")
    add_evidence(
        investigation["id"],
        evidence_type="UNDERCOVER_BUY",
        observed_at="2026-07-15T00:00:00Z",
        note="Clerk exchanged $200 of benefits for $100 cash.",
    )
    add_evidence(
        investigation["id"],
        evidence_type="EBT_ONLY_TRANSACTION_PATTERN",
        observed_at="2026-07-20T00:00:00Z",
    )
    return conclude_investigation(investigation["id"], "TRAFFICKING")


# --------------------------------------------------------------------------
# Sanction cases
# --------------------------------------------------------------------------

def open_case(investigation_id: str, violation_type: str, **overrides: Any) -> Dict[str, Any]:
    return created(
        api_client.create_sanction_case(
            f.sanction_case_payload(investigation_id, violation_type, **overrides), ADMIN
        )
    )


def issue_charge_letter(case_id: str, **overrides: Any) -> Dict[str, Any]:
    return ok(
        api_client.issue_charge_letter(case_id, f.charge_letter_payload(**overrides), ADMIN)
    )


def file_reply(case_id: str, owner: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    return ok(
        api_client.file_reply(case_id, f.reply_payload(**overrides), owner_headers(owner))
    )


def elect_cmp(case: Dict[str, Any], owner: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """The election is guarded by the case version the retailer last read."""
    payload = f.cmp_election_payload(case["version"], **overrides)
    return created(
        api_client.create_cmp_election(case["id"], payload, owner_headers(owner))
    )


def issue_determination(case_id: str, sanction_type: str) -> Dict[str, Any]:
    return ok(
        api_client.issue_determination(
            case_id, f.determination_payload(sanction_type), ADMIN
        )
    )


def finalize_case(case_id: str) -> Dict[str, Any]:
    return ok(api_client.finalize_sanction_case(case_id, ADMIN))


def enforce_case(case_id: str) -> Dict[str, Any]:
    return ok(api_client.enforce_sanction_case(case_id, ADMIN))


def ledger_entries(case_id: str) -> List[Dict[str, Any]]:
    return rows(api_client.list_penalty_ledger(case_id, ADMIN))


def charged_case(
    context: AuthorizedStore, violation_type: str = "INELIGIBLE_ITEMS_HARDSHIP"
) -> Dict[str, Any]:
    """A substantiated investigation, a sanction case and its charge letter, which
    is what starts both ten-day clocks."""
    if violation_type == "TRAFFICKING":
        investigation = substantiated_trafficking_investigation(context.store_id)
    else:
        investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], violation_type)
    return issue_charge_letter(case["id"])


def replied_case(
    context: AuthorizedStore,
    violation_type: str = "INELIGIBLE_ITEMS_HARDSHIP",
    with_election: bool = False,
) -> Dict[str, Any]:
    """A charged case answered by the retailer, optionally with a timely
    civil-money-penalty election on file first."""
    case = charged_case(context, violation_type)
    if with_election:
        elect_cmp(case, context.owner)
    file_reply(case["id"], context.owner)
    return refresh_case(case["id"])
