"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints
only, and uses the lenient success validator so a broken setup step reports
itself clearly rather than surfacing as a confusing assertion failure later.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_BREAKPOINT_TIERS,
    MONDAY,
    NO_LOAD_BREAKPOINT_TIERS,
    SINGLE_TIER_BREAKPOINT_TIERS,
    TEST_DEFAULTS,
    TUESDAY,
    TWO_TIER_BREAKPOINT_TIERS,
    WEDNESDAY,
)
from .factories import (
    create_blue_sky_registration_payload,
    create_distribution_payload,
    create_exchange_payload,
    create_fund_payload,
    create_nav_record_payload,
    create_purchase_payload,
    create_redemption_payload,
    create_share_class_payload,
    create_shareholder_account_payload,
    create_systematic_plan_payload,
    create_pricing_error_case_payload,
)
from .test_users import (
    TEST_USERS,
    make_accountant_headers,
    make_compliance_headers,
)

OPERATOR = TEST_USERS["operator_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
DEALER = TEST_USERS["dealer_headers"]

CLOCK_MONDAY_MORNING = "2026-08-03T09:00:00Z"
CLOCK_TUESDAY_MORNING = "2026-08-04T09:00:00Z"
CLOCK_WEDNESDAY_MORNING = "2026-08-05T09:00:00Z"


# ============================================================ Tier 0: primitives
def set_clock(to_iso8601: str, headers=None) -> dict:
    """Move the logical clock every date and time rule reads."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or ACCOUNTANT))


def create_fund(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_fund(create_fund_payload(**overrides), headers or ACCOUNTANT)
    )


def create_share_class(fund_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_share_class(
            create_share_class_payload(fund_id, **overrides), headers or ACCOUNTANT
        )
    )


def create_registration(share_class_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_blue_sky_registration(
            create_blue_sky_registration_payload(share_class_id, **overrides),
            headers or COMPLIANCE,
        )
    )


def open_account(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_shareholder_account(
            create_shareholder_account_payload(**overrides), headers or OPERATOR
        )
    )


def activate_account(account_id: str, tin_certified: bool = True, headers=None) -> dict:
    return get_success_data(
        api_client.activate_shareholder_account(
            account_id, {"tin_certified": tin_certified}, headers or OPERATOR
        )
    )


def open_active_account(tin_certified: bool = True, headers=None, **overrides) -> dict:
    """Open an account and record receipt of its documents, returning the ACTIVE row."""
    account = open_account(headers=headers, **overrides)
    return activate_account(account["id"], tin_certified=tin_certified, headers=headers)


def strike_nav(share_class_id: str, valuation_date: str, total_net_assets: float = 0.00,
               finalize: bool = True, headers=None) -> dict:
    """Strike a NAV for a class and date, optionally finalizing it."""
    record = get_success_data(
        api_client.create_nav_record(
            create_nav_record_payload(
                share_class_id,
                valuation_date=valuation_date,
                total_net_assets=total_net_assets,
            ),
            headers or ACCOUNTANT,
        )
    )
    if finalize:
        record = get_success_data(
            api_client.finalize_nav_record(record["id"], headers or ACCOUNTANT)
        )
    return record


def capture_purchase(account_id: str, share_class_id: str, gross_amount: float,
                     headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_trade(
            create_purchase_payload(account_id, share_class_id, gross_amount, **overrides),
            headers or OPERATOR,
        )
    )


def capture_redemption(account_id: str, share_class_id: str, shares_requested: float,
                       headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_trade(
            create_redemption_payload(
                account_id, share_class_id, shares_requested, **overrides
            ),
            headers or OPERATOR,
        )
    )


def capture_exchange(account_id: str, share_class_id: str, shares_requested: float,
                     target_share_class_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_trade(
            create_exchange_payload(
                account_id, share_class_id, shares_requested,
                target_share_class_id, **overrides,
            ),
            headers or OPERATOR,
        )
    )


def price_trade(trade_id: str, headers=None) -> dict:
    return get_success_data(api_client.price_trade(trade_id, headers or OPERATOR))


def settle_trade(trade_id: str, headers=None) -> dict:
    return get_success_data(api_client.settle_trade(trade_id, headers or OPERATOR))


def buy_and_settle(account_id: str, share_class_id: str, gross_amount: float,
                   headers=None, **overrides) -> dict:
    """Capture, price and settle one purchase. Returns the settled trade."""
    trade = capture_purchase(
        account_id, share_class_id, gross_amount, headers=headers, **overrides
    )
    price_trade(trade["id"])
    return settle_trade(trade["id"])


def redeem_and_settle(account_id: str, share_class_id: str, shares_requested: float,
                      headers=None, **overrides) -> dict:
    trade = capture_redemption(
        account_id, share_class_id, shares_requested, headers=headers, **overrides
    )
    price_trade(trade["id"])
    return settle_trade(trade["id"])


def read_account(account_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_shareholder_account(account_id, headers or OPERATOR)
    )


def read_trade(trade_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_trade(trade_id, headers or OPERATOR))


def read_share_class(share_class_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_share_class(share_class_id, headers or OPERATOR))


def read_registration(registration_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_blue_sky_registration(registration_id, headers or COMPLIANCE)
    )


def read_nav_record(nav_record_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_nav_record(nav_record_id, headers or ACCOUNTANT))


def read_case(case_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_pricing_error_case(case_id, headers or ACCOUNTANT)
    )


def read_plan(plan_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_systematic_plan(plan_id, headers or OPERATOR))


def read_distribution(distribution_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_distribution(distribution_id, headers or ACCOUNTANT)
    )


def read_reconciliation(reconciliation_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_omnibus_reconciliation(reconciliation_id, headers or COMPLIANCE)
    )


def only_position(account_id: str, headers=None) -> dict:
    """The single position of an account; fails loudly when there is not exactly one."""
    body = get_success_data(
        api_client.list_positions(headers or OPERATOR, params={"account_id": account_id})
    )
    assert len(body) == 1, f"expected exactly one position for {account_id}, got {len(body)}"
    return body[0]


def position_for(account_id: str, share_class_id: str, headers=None) -> dict:
    body = get_success_data(
        api_client.list_positions(
            headers or OPERATOR,
            params={"account_id": account_id, "share_class_id": share_class_id},
        )
    )
    assert len(body) == 1, (
        f"expected exactly one position for {account_id}/{share_class_id}, got {len(body)}"
    )
    return body[0]


def ledger_entries_for_trade(trade_id: str, headers=None) -> list:
    return get_success_data(
        api_client.list_share_ledger_entries(
            headers or OPERATOR, params={"trade_id": trade_id}
        )
    )


def ledger_entries_for_position(position_id: str, headers=None) -> list:
    return get_success_data(
        api_client.list_share_ledger_entries(
            headers or OPERATOR, params={"position_id": position_id}
        )
    )


def payments_for_distribution(distribution_id: str, headers=None) -> list:
    return get_success_data(
        api_client.list_distribution_payments(
            headers or ACCOUNTANT, params={"distribution_id": distribution_id}
        )
    )


def payment_for_account(distribution_id: str, account_id: str, headers=None) -> dict:
    body = get_success_data(
        api_client.list_distribution_payments(
            headers or ACCOUNTANT,
            params={"distribution_id": distribution_id, "account_id": account_id},
        )
    )
    assert len(body) == 1, (
        f"expected exactly one payment for account {account_id}, got {len(body)}"
    )
    return body[0]


# ====================================================== Tier 1: reference data
def setup_reference_data(clock: str = CLOCK_MONDAY_MORNING,
                         tiers=None,
                         state_code: str = "CA",
                         registered_amount: float = None,
                         with_registration: bool = True,
                         fund_overrides: dict = None,
                         class_overrides: dict = None) -> dict:
    """Move the clock, register a fund and one share class, and file one state
    registration covering the whole of 2026.

    Returns {"fund", "share_class", "registration"}.
    """
    if clock:
        set_clock(clock)
    fund = create_fund(**(fund_overrides or {}))
    class_kwargs = {"breakpoint_tiers": list(tiers or DEFAULT_BREAKPOINT_TIERS)}
    class_kwargs.update(class_overrides or {})
    share_class = create_share_class(fund["id"], **class_kwargs)
    registration = None
    if with_registration:
        registration = create_registration(
            share_class["id"],
            state_code=state_code,
            registered_amount=(
                registered_amount
                if registered_amount is not None
                else TEST_DEFAULTS["REGISTERED_AMOUNT"]
            ),
        )
    return {"fund": fund, "share_class": share_class, "registration": registration}


def setup_trading_desk(clock: str = CLOCK_MONDAY_MORNING,
                       tiers=None,
                       state_code: str = "CA",
                       registered_amount: float = None,
                       account_channel: str = "DIRECT",
                       registration_type: str = "INDIVIDUAL",
                       dividend_option: str = "CASH",
                       tin_certified: bool = True,
                       class_overrides: dict = None,
                       fund_overrides: dict = None,
                       seed_nav_date: str = MONDAY,
                       strike_seed_nav: bool = True,
                       account_overrides: dict = None) -> dict:
    """Reference data plus one ACTIVE account and, by default, a FINAL seed NAV.

    Returns {"fund", "share_class", "registration", "account", "nav"}.
    """
    base = setup_reference_data(
        clock=clock, tiers=tiers, state_code=state_code,
        registered_amount=registered_amount,
        fund_overrides=fund_overrides, class_overrides=class_overrides,
    )
    account_kwargs = {
        "account_channel": account_channel,
        "registration_type": registration_type,
        "state_code": state_code,
        "dividend_option": dividend_option,
    }
    if account_channel in ("NETWORKED", "OMNIBUS"):
        account_kwargs["dealer_firm_code"] = "DLR001"
    account_kwargs.update(account_overrides or {})
    account = open_active_account(tin_certified=tin_certified, **account_kwargs)
    nav = None
    if strike_seed_nav:
        nav = strike_nav(base["share_class"]["id"], seed_nav_date, 0.00, finalize=True)
    base["account"] = account
    base["nav"] = nav
    return base


def setup_settled_purchase(gross_amount: float = 60000.00, **kwargs) -> dict:
    """A trading desk whose account already holds a settled purchase.

    With the default three-tier schedule and a 10.0000 seed NAV, a 60000.00
    purchase is charged 0.045 and books 5730.000 shares.
    """
    desk = setup_trading_desk(**kwargs)
    trade = buy_and_settle(desk["account"]["id"], desk["share_class"]["id"], gross_amount)
    desk["trade"] = trade
    desk["position"] = only_position(desk["account"]["id"])
    desk["account"] = read_account(desk["account"]["id"])
    return desk


# ============================== Tier 2: rights-of-accumulation basis divergence
def setup_dual_channel_household() -> dict:
    """A DIRECT and an OMNIBUS account holding byte-identical positions.

    Both buy 60000.00 at the 10.0000 seed NAV on Monday (0.045 tier, 57300.00
    net, 5730.000 shares, 60000.00 cost basis). Tuesday's NAV is struck at
    11.0000 from 126060.00 of net assets over the 11460.000 combined shares, so
    the direct account marks to 63030.00 while the omnibus account stays at its
    60000.00 historical cost.

    Returns {"share_class", "registration", "direct_account", "omnibus_account",
             "nav_monday", "nav_tuesday"}.
    """
    base = setup_reference_data(tiers=DEFAULT_BREAKPOINT_TIERS)
    share_class_id = base["share_class"]["id"]

    direct_account = open_active_account(
        account_channel="DIRECT", state_code="CA", primary_owner_name="Ada Direct"
    )
    omnibus_account = open_active_account(
        account_channel="OMNIBUS", state_code="CA",
        primary_owner_name="Omni Nominee", dealer_firm_code="DLR001",
    )
    nav_monday = strike_nav(share_class_id, MONDAY, 0.00, finalize=True)

    buy_and_settle(direct_account["id"], share_class_id, 60000.00)
    buy_and_settle(omnibus_account["id"], share_class_id, 60000.00)

    set_clock(CLOCK_TUESDAY_MORNING)
    nav_tuesday = strike_nav(share_class_id, TUESDAY, 126060.00, finalize=True)

    return {
        "fund": base["fund"],
        "share_class": base["share_class"],
        "registration": base["registration"],
        "direct_account": read_account(direct_account["id"]),
        "omnibus_account": read_account(omnibus_account["id"]),
        "nav_monday": nav_monday,
        "nav_tuesday": nav_tuesday,
    }


def setup_linked_household() -> dict:
    """A primary account holding 5730.000 shares and a linked secondary holding
    nothing, with Tuesday's NAV struck at 11.0000.

    Returns {"share_class", "primary_account", "secondary_account", "nav_tuesday"}.
    """
    base = setup_reference_data(tiers=DEFAULT_BREAKPOINT_TIERS)
    share_class_id = base["share_class"]["id"]

    primary = open_active_account(primary_owner_name="Head Household")
    secondary = open_active_account(
        registration_type="UGMA_UTMA",
        primary_owner_name="Child Household",
        linked_primary_account_id=primary["id"],
    )
    strike_nav(share_class_id, MONDAY, 0.00, finalize=True)
    buy_and_settle(primary["id"], share_class_id, 60000.00)

    set_clock(CLOCK_TUESDAY_MORNING)
    nav_tuesday = strike_nav(share_class_id, TUESDAY, 63030.00, finalize=True)

    return {
        "share_class": base["share_class"],
        "primary_account": read_account(primary["id"]),
        "secondary_account": read_account(secondary["id"]),
        "nav_tuesday": nav_tuesday,
    }


# ================================ Tier 2: provisional versus final NAV pricing
def setup_provisional_pricing_scenario() -> dict:
    """A class with 5730.000 shares on the books and Tuesday's NAV left
    PRELIMINARY at 11.0000 (63030.00 of net assets over 5730.000 shares).

    Returns {"share_class", "buyer_account", "nav_tuesday"}.
    """
    base = setup_reference_data(tiers=DEFAULT_BREAKPOINT_TIERS)
    share_class_id = base["share_class"]["id"]

    seed_holder = open_active_account(primary_owner_name="Seed Holder")
    buyer = open_active_account(primary_owner_name="Pat Buyer")

    strike_nav(share_class_id, MONDAY, 0.00, finalize=True)
    buy_and_settle(seed_holder["id"], share_class_id, 60000.00)

    set_clock(CLOCK_TUESDAY_MORNING)
    nav_tuesday = strike_nav(share_class_id, TUESDAY, 63030.00, finalize=False)

    return {
        "share_class": base["share_class"],
        "seed_account": read_account(seed_holder["id"]),
        "buyer_account": read_account(buyer["id"]),
        "nav_tuesday": nav_tuesday,
    }


# ==================================================== Tier 3: distribution flows
def setup_three_holder_income_distribution() -> dict:
    """Three settled holders and one DECLARED income distribution of 0.1234.

    Holdings after Monday's settlements are 4524.000, 2356.250 and 754.000
    shares; Tuesday's NAV is struck at 11.0000 from 83976.75 of net assets.
    The third holder is not TIN certified, so its payment carries backup
    withholding.

    Returns {"share_class", "reinvest_account", "cash_account",
             "uncertified_account", "distribution", "nav_tuesday"}.
    """
    base = setup_reference_data(tiers=DEFAULT_BREAKPOINT_TIERS)
    share_class_id = base["share_class"]["id"]

    reinvest_account = open_active_account(
        dividend_option="REINVEST", tin_certified=True, primary_owner_name="Rita Reinvest"
    )
    cash_account = open_active_account(
        dividend_option="CASH", tin_certified=True, primary_owner_name="Carl Cash"
    )
    uncertified_account = open_active_account(
        dividend_option="REINVEST", tin_certified=False,
        primary_owner_name="Uma Uncertified",
    )

    strike_nav(share_class_id, MONDAY, 0.00, finalize=True)
    buy_and_settle(reinvest_account["id"], share_class_id, 48000.00)
    buy_and_settle(cash_account["id"], share_class_id, 25000.00)
    buy_and_settle(uncertified_account["id"], share_class_id, 8000.00)

    set_clock(CLOCK_TUESDAY_MORNING)
    nav_tuesday = strike_nav(share_class_id, TUESDAY, 83976.75, finalize=True)

    distribution = get_success_data(
        api_client.create_distribution(
            create_distribution_payload(
                share_class_id,
                rate_per_share=0.1234,
                record_date=TUESDAY, ex_date=TUESDAY, pay_date=WEDNESDAY,
            ),
            ACCOUNTANT,
        )
    )

    return {
        "share_class": base["share_class"],
        "reinvest_account": read_account(reinvest_account["id"]),
        "cash_account": read_account(cash_account["id"]),
        "uncertified_account": read_account(uncertified_account["id"]),
        "distribution": distribution,
        "nav_tuesday": nav_tuesday,
    }


def setup_recorded_reinvest_distribution() -> dict:
    """One reinvesting holder of 4524.000 shares with the distribution already
    RECORDED and the clock advanced past the pay date.

    Returns {"share_class", "account", "distribution", "nav_tuesday", "position"}.
    """
    base = setup_reference_data(tiers=DEFAULT_BREAKPOINT_TIERS)
    share_class_id = base["share_class"]["id"]

    account = open_active_account(
        dividend_option="REINVEST", tin_certified=True, primary_owner_name="Rae Reinvestor"
    )
    strike_nav(share_class_id, MONDAY, 0.00, finalize=True)
    buy_and_settle(account["id"], share_class_id, 48000.00)

    set_clock(CLOCK_TUESDAY_MORNING)
    nav_tuesday = strike_nav(share_class_id, TUESDAY, 49764.00, finalize=True)

    distribution = get_success_data(
        api_client.create_distribution(
            create_distribution_payload(
                share_class_id,
                rate_per_share=0.1234,
                record_date=TUESDAY, ex_date=TUESDAY, pay_date=WEDNESDAY,
            ),
            ACCOUNTANT,
        )
    )
    set_clock("2026-08-04T17:00:00Z")
    get_success_data(api_client.record_distribution(distribution["id"], ACCOUNTANT))
    set_clock("2026-08-05T10:00:00Z")

    return {
        "share_class": base["share_class"],
        "account": read_account(account["id"]),
        "distribution": read_distribution(distribution["id"]),
        "nav_tuesday": nav_tuesday,
        "position": only_position(account["id"]),
    }


def setup_declared_income_distribution_window() -> dict:
    """One share class with an ORDINARY_INCOME declaration running record
    2026-08-10 through pay 2026-08-14.

    Returns {"share_class", "distribution"}.
    """
    base = setup_reference_data(
        tiers=SINGLE_TIER_BREAKPOINT_TIERS, with_registration=False
    )
    distribution = get_success_data(
        api_client.create_distribution(
            create_distribution_payload(
                base["share_class"]["id"],
                rate_per_share=0.1000,
                record_date="2026-08-10", ex_date="2026-08-11", pay_date="2026-08-14",
            ),
            ACCOUNTANT,
        )
    )
    return {"share_class": base["share_class"], "distribution": distribution}


# ============================================== Tier 4: pricing error workflows
def setup_finalized_nav_for_case(seed_nav: float = 11.0000,
                                 class_code: str = "I") -> dict:
    """A share class with no shares outstanding whose NAV therefore strikes at
    the seed price, finalized and ready for a pricing error case.

    Returns {"share_class", "nav"}.
    """
    base = setup_reference_data(
        tiers=NO_LOAD_BREAKPOINT_TIERS,
        with_registration=False,
        fund_overrides={"name": "Meridian Income Fund"},
        class_overrides={"class_code": class_code, "seed_nav_per_share": seed_nav},
    )
    nav = strike_nav(base["share_class"]["id"], MONDAY, 0.00, finalize=True)
    return {"share_class": base["share_class"], "nav": nav}


def open_case(nav_record: dict, corrected_nav_per_share: float,
              detected_by: str = "fa-1", error_reason: str = None,
              expected_version: int = None) -> dict:
    """Open a pricing error case against a finalized NAV record."""
    payload = create_pricing_error_case_payload(
        nav_record["id"],
        corrected_nav_per_share,
        expected_version if expected_version is not None else nav_record["version"],
    )
    if error_reason:
        payload["error_reason"] = error_reason
    return get_success_data(
        api_client.create_pricing_error_case(payload, make_accountant_headers(detected_by))
    )


def assess_case(case_id: str, actor: str = "fa-1") -> dict:
    return get_success_data(
        api_client.assess_pricing_error_case(case_id, make_accountant_headers(actor))
    )


def approve_case(case_id: str, actor: str = "co-1") -> dict:
    return get_success_data(
        api_client.approve_correction_pricing_error_case(
            case_id, make_compliance_headers(actor)
        )
    )


def setup_assessed_boundary_cases() -> dict:
    """Two classes seeded at 11.0000 with zero shares, each carrying a DETECTED
    case: one proposing 11.0550 (exactly 50.00 bps) and one proposing 11.0540
    (49.09 bps).

    Returns {"material_case", "immaterial_case", "material_nav", "immaterial_nav"}.
    """
    set_clock(CLOCK_MONDAY_MORNING)
    fund = create_fund(name="Meridian Income Fund")
    class_material = create_share_class(
        fund["id"], class_code="I", seed_nav_per_share=11.0000,
        breakpoint_tiers=list(NO_LOAD_BREAKPOINT_TIERS),
    )
    class_immaterial = create_share_class(
        fund["id"], class_code="C", seed_nav_per_share=11.0000,
        breakpoint_tiers=list(NO_LOAD_BREAKPOINT_TIERS),
    )
    nav_material = strike_nav(class_material["id"], MONDAY, 0.00, finalize=True)
    nav_immaterial = strike_nav(class_immaterial["id"], MONDAY, 0.00, finalize=True)

    case_material = open_case(
        nav_material, 11.0550, error_reason="Exactly at the materiality threshold"
    )
    case_immaterial = open_case(
        nav_immaterial, 11.0540, error_reason="One ten-thousandth below the threshold"
    )
    return {
        "material_nav": nav_material,
        "immaterial_nav": nav_immaterial,
        "material_case": case_material,
        "immaterial_case": case_immaterial,
    }


def setup_two_dated_settled_purchases() -> dict:
    """Monday's 60000.00 purchase (5730.000 shares at the 10.0000 seed) and
    Tuesday's 22000.00 purchase (1885.000 shares at 11.0000), both settled.

    Returns {"share_class", "monday_account", "tuesday_account", "monday_trade",
             "tuesday_trade", "nav_monday", "nav_tuesday"}.
    """
    base = setup_reference_data(tiers=DEFAULT_BREAKPOINT_TIERS)
    share_class_id = base["share_class"]["id"]

    monday_account = open_active_account(primary_owner_name="Xavier Immaterial")
    nav_monday = strike_nav(share_class_id, MONDAY, 0.00, finalize=True)
    monday_trade = buy_and_settle(monday_account["id"], share_class_id, 60000.00)

    set_clock(CLOCK_TUESDAY_MORNING)
    tuesday_account = open_active_account(primary_owner_name="Yara Material")
    nav_tuesday = strike_nav(share_class_id, TUESDAY, 63030.00, finalize=True)
    tuesday_trade = buy_and_settle(tuesday_account["id"], share_class_id, 22000.00)

    return {
        "share_class": base["share_class"],
        "monday_account": read_account(monday_account["id"]),
        "tuesday_account": read_account(tuesday_account["id"]),
        "monday_trade": monday_trade,
        "tuesday_trade": tuesday_trade,
        "nav_monday": nav_monday,
        "nav_tuesday": nav_tuesday,
    }


def setup_five_link_cascade() -> dict:
    """The full reprocessing cascade preconditions.

    Monday: 60000.00 settled at 10.0000 (5730.000 shares).
    Tuesday: NAV 11.0000 FINAL, 22000.00 settled (1885.000 shares); class 7615.000.
    Wednesday: NAV struck at 11.0000 and left PRELIMINARY, with a 10000.00
    purchase priced provisionally against it at 856.818 shares.
    A MATERIAL_APPROVED case proposing 11.0550 sits on Tuesday's record.

    Returns {"share_class", "case", "monday_trade", "tuesday_trade",
             "provisional_trade", "nav_tuesday", "nav_wednesday",
             "tuesday_account"}.
    """
    base = setup_reference_data(tiers=DEFAULT_BREAKPOINT_TIERS)
    share_class_id = base["share_class"]["id"]

    first = open_active_account(primary_owner_name="First Holder")
    strike_nav(share_class_id, MONDAY, 0.00, finalize=True)
    monday_trade = buy_and_settle(first["id"], share_class_id, 60000.00)

    set_clock(CLOCK_TUESDAY_MORNING)
    second = open_active_account(primary_owner_name="Second Holder")
    nav_tuesday = strike_nav(share_class_id, TUESDAY, 63030.00, finalize=True)
    tuesday_trade = buy_and_settle(second["id"], share_class_id, 22000.00)

    set_clock(CLOCK_WEDNESDAY_MORNING)
    third = open_active_account(primary_owner_name="Third Holder")
    nav_wednesday = strike_nav(share_class_id, WEDNESDAY, 83765.00, finalize=False)
    provisional_trade = capture_purchase(third["id"], share_class_id, 10000.00)
    provisional_trade = price_trade(provisional_trade["id"])

    case = open_case(
        nav_tuesday, 11.0550,
        error_reason="Fair value adjustment omitted from the 08-04 strike",
    )
    assess_case(case["id"])
    approve_case(case["id"])

    return {
        "share_class": base["share_class"],
        "case": read_case(case["id"]),
        "monday_trade": monday_trade,
        "tuesday_trade": tuesday_trade,
        "provisional_trade": provisional_trade,
        "nav_tuesday": nav_tuesday,
        "nav_wednesday": nav_wednesday,
        "first_account": read_account(first["id"]),
        "tuesday_account": read_account(second["id"]),
        "third_account": read_account(third["id"]),
    }


def setup_material_case_awaiting_reprocess() -> dict:
    """A MATERIAL_APPROVED case opened by fa-1 on a seed-priced 11.0000 record.

    Returns {"case", "nav", "share_class"}.
    """
    ref = setup_finalized_nav_for_case()
    case = open_case(ref["nav"], 11.0600, error_reason="Missed accrual")
    assess_case(case["id"])
    approve_case(case["id"])
    return {"case": read_case(case["id"]), "nav": ref["nav"], "share_class": ref["share_class"]}


def setup_trade_awaiting_nav_under_review() -> dict:
    """A captured 30000.00 purchase whose pricing NAV was pushed to
    UNDER_ERROR_REVIEW by a freshly opened case.

    Returns {"share_class", "registration", "account", "trade", "nav", "case"}.
    """
    desk = setup_trading_desk(tiers=TWO_TIER_BREAKPOINT_TIERS)
    trade = capture_purchase(
        desk["account"]["id"], desk["share_class"]["id"], 30000.00
    )
    case = open_case(
        desk["nav"], 10.2000, error_reason="Security priced with a stale quote"
    )
    return {
        "share_class": desk["share_class"],
        "registration": read_registration(desk["registration"]["id"]),
        "account": desk["account"],
        "trade": trade,
        "nav": read_nav_record(desk["nav"]["id"]),
        "case": case,
    }


# ============================================ Tier 5: registrations and capacity
def setup_exact_capacity_registration() -> dict:
    """An NV registration of exactly 50000.00 with nothing reserved or consumed,
    plus an ACTIVE NV account and a FINAL seed NAV.

    Returns {"share_class", "registration", "account", "nav"}.
    """
    return setup_trading_desk(
        tiers=TWO_TIER_BREAKPOINT_TIERS,
        state_code="NV",
        registered_amount=50000.00,
        account_overrides={"primary_owner_name": "Edge Holder"},
    )


def setup_closed_account_against_small_registration() -> dict:
    """An NV registration of 50000.00 and an account that was activated and then
    closed while holding nothing.

    Returns {"share_class", "registration", "account", "nav"}.
    """
    desk = setup_trading_desk(
        tiers=TWO_TIER_BREAKPOINT_TIERS,
        state_code="NV",
        registered_amount=50000.00,
        strike_seed_nav=False,
        account_overrides={"primary_owner_name": "Clara Closed"},
    )
    get_success_data(
        api_client.close_shareholder_account(desk["account"]["id"], OPERATOR)
    )
    desk["nav"] = strike_nav(desk["share_class"]["id"], MONDAY, 0.00, finalize=True)
    desk["account"] = read_account(desk["account"]["id"])
    return desk


def setup_unregistered_state_account() -> dict:
    """A class registered only in CA and an ACTIVE TX account, with the clock
    moved to Friday 2026-08-07 — four business days after Monday 2026-08-03.

    Returns {"share_class", "registration", "account"}.
    """
    base = setup_reference_data(tiers=SINGLE_TIER_BREAKPOINT_TIERS, state_code="CA")
    account = open_active_account(state_code="TX", primary_owner_name="Tex Holder")
    strike_nav(base["share_class"]["id"], MONDAY, 0.00, finalize=True)
    set_clock("2026-08-07T10:00:00Z")
    return {
        "share_class": base["share_class"],
        "registration": base["registration"],
        "account": read_account(account["id"]),
    }


def setup_single_registration_window() -> dict:
    """One CA registration covering 2026-01-01 through 2026-09-01 for 400000.00.

    Returns {"share_class", "registration"}.
    """
    set_clock(CLOCK_MONDAY_MORNING)
    fund = create_fund()
    share_class = create_share_class(
        fund["id"], breakpoint_tiers=list(SINGLE_TIER_BREAKPOINT_TIERS)
    )
    registration = create_registration(
        share_class["id"], state_code="CA", registered_amount=400000.00,
        effective_date="2026-01-01", expiration_date="2026-09-01",
    )
    return {"share_class": share_class, "registration": registration}


def setup_capacity_identity_desk() -> dict:
    """An NV registration of exactly 50000.00 with an ACTIVE corporate account
    and a FINAL seed NAV, ready for capture / settle / cancel / reverse.

    Returns {"share_class", "registration", "account", "nav"}.
    """
    return setup_trading_desk(
        tiers=TWO_TIER_BREAKPOINT_TIERS,
        state_code="NV",
        registered_amount=50000.00,
        registration_type="CORPORATE",
        account_overrides={"primary_owner_name": "Vault Corp"},
    )


def setup_two_settled_purchases_same_class() -> dict:
    """Two accounts holding 5730.000 and 2356.250 shares of the same class from
    settled 60000.00 and 25000.00 purchases at the 10.0000 seed NAV.

    Returns {"share_class", "main_account", "neighbour_account", "main_trade",
             "neighbour_trade"}.
    """
    base = setup_reference_data(tiers=TWO_TIER_BREAKPOINT_TIERS)
    share_class_id = base["share_class"]["id"]

    main = open_active_account(primary_owner_name="Mona Main")
    neighbour = open_active_account(primary_owner_name="Ned Neighbour")
    strike_nav(share_class_id, MONDAY, 0.00, finalize=True)

    main_trade = buy_and_settle(main["id"], share_class_id, 60000.00)
    neighbour_trade = buy_and_settle(neighbour["id"], share_class_id, 25000.00)

    return {
        "share_class": base["share_class"],
        "main_account": read_account(main["id"]),
        "neighbour_account": read_account(neighbour["id"]),
        "main_trade": main_trade,
        "neighbour_trade": neighbour_trade,
    }


# ================================================= Tier 6: restrictions and CDSC
def setup_restricted_account_holding_shares() -> dict:
    """An account holding 5730.000 shares that compliance has restricted, with
    Tuesday's NAV struck at 11.0000 and FINAL.

    Returns {"share_class", "registration", "account", "nav_tuesday"}.
    """
    desk = setup_trading_desk(
        tiers=TWO_TIER_BREAKPOINT_TIERS,
        registration_type="JOINT_TENANTS",
        account_overrides={"primary_owner_name": "Rex Restricted"},
    )
    buy_and_settle(desk["account"]["id"], desk["share_class"]["id"], 60000.00)

    set_clock(CLOCK_TUESDAY_MORNING)
    nav_tuesday = strike_nav(desk["share_class"]["id"], TUESDAY, 63030.00, finalize=True)
    get_success_data(
        api_client.restrict_shareholder_account(
            desk["account"]["id"],
            {"restriction_reason": "Pending anti-money-laundering review"},
            COMPLIANCE,
        )
    )
    desk["account"] = read_account(desk["account"]["id"])
    desk["nav_tuesday"] = nav_tuesday
    return desk


def setup_cdsc_position() -> dict:
    """A CDSC-enabled, load-free class holding 2000.000 shares bought for
    20000.00 on Monday, with Wednesday's NAV struck at 12.0000 and FINAL.

    Returns {"share_class", "registration", "account", "nav_wednesday"}.
    """
    desk = setup_trading_desk(
        tiers=NO_LOAD_BREAKPOINT_TIERS,
        class_overrides={"class_code": "C", "cdsc_enabled": True},
        account_overrides={"primary_owner_name": "Cid Deferred"},
    )
    purchase = buy_and_settle(desk["account"]["id"], desk["share_class"]["id"], 20000.00)

    set_clock(CLOCK_WEDNESDAY_MORNING)
    nav_wednesday = strike_nav(desk["share_class"]["id"], WEDNESDAY, 24000.00, finalize=True)

    desk["purchase"] = purchase
    desk["nav_wednesday"] = nav_wednesday
    return desk


def setup_same_fund_exchange() -> dict:
    """One fund with class A (seed 10.0000) and class B (seed 20.0000), both
    registered in CA, and an account holding 5730.000 class A shares. Tuesday's
    NAVs are 11.0000 for class A and 20.0000 for class B, both FINAL.

    Returns {"fund", "source_class", "target_class", "source_registration",
             "target_registration", "account", "nav_source", "nav_target"}.
    """
    set_clock(CLOCK_MONDAY_MORNING)
    fund = create_fund()
    source_class = create_share_class(
        fund["id"], class_code="A", seed_nav_per_share=10.0000,
        breakpoint_tiers=list(TWO_TIER_BREAKPOINT_TIERS),
    )
    target_class = create_share_class(
        fund["id"], class_code="B", seed_nav_per_share=20.0000,
        breakpoint_tiers=list(SINGLE_TIER_BREAKPOINT_TIERS),
    )
    source_registration = create_registration(source_class["id"], state_code="CA")
    target_registration = create_registration(target_class["id"], state_code="CA")

    account = open_active_account(primary_owner_name="Xena Exchange")
    strike_nav(source_class["id"], MONDAY, 0.00, finalize=True)
    buy_and_settle(account["id"], source_class["id"], 60000.00)

    set_clock(CLOCK_TUESDAY_MORNING)
    nav_source = strike_nav(source_class["id"], TUESDAY, 63030.00, finalize=True)
    nav_target = strike_nav(target_class["id"], TUESDAY, 0.00, finalize=True)

    return {
        "fund": fund,
        "source_class": source_class,
        "target_class": target_class,
        "source_registration": source_registration,
        "target_registration": target_registration,
        "account": read_account(account["id"]),
        "nav_source": nav_source,
        "nav_target": nav_target,
    }


# ============================================ Tier 7: plans and reconciliations
def create_plan(account_id: str, source_share_class_id: str, headers=None,
                **overrides) -> dict:
    """Create a systematic plan, presenting the account's current version."""
    account = read_account(account_id)
    payload = create_systematic_plan_payload(
        account_id, source_share_class_id, account["version"], **overrides
    )
    return get_success_data(
        api_client.create_systematic_plan(payload, headers or OPERATOR)
    )


def setup_account_with_investment_plan(amount: float = 500.00,
                                       next_run_date: str = "2026-09-01") -> dict:
    """An ACTIVE account carrying one ACTIVE monthly investment plan.

    Returns {"share_class", "account", "plan", "account_version_at_activation"}.
    """
    base = setup_reference_data(
        tiers=SINGLE_TIER_BREAKPOINT_TIERS, with_registration=True
    )
    account = open_active_account(primary_owner_name="Wendy Plan")
    plan = create_plan(
        account["id"], base["share_class"]["id"],
        amount=amount, next_run_date=next_run_date,
    )
    return {
        "share_class": base["share_class"],
        "registration": base["registration"],
        "account": read_account(account["id"]),
        "account_version_at_activation": account["version"],
        "plan": plan,
    }


def setup_due_investment_plan() -> dict:
    """A monthly 500.00 investment plan due 2026-08-05 with the clock on that day.

    Returns {"share_class", "registration", "account", "plan"}.
    """
    base = setup_reference_data(tiers=SINGLE_TIER_BREAKPOINT_TIERS)
    account = open_active_account(
        registration_type="ROTH_IRA", primary_owner_name="Stan Plan"
    )
    plan = create_plan(
        account["id"], base["share_class"]["id"],
        amount=500.00, next_run_date=WEDNESDAY,
    )
    set_clock(CLOCK_WEDNESDAY_MORNING)
    return {
        "share_class": base["share_class"],
        "registration": base["registration"],
        "account": read_account(account["id"]),
        "plan": plan,
    }


def setup_underfunded_withdrawal_plan() -> dict:
    """An account holding 2827.500 shares worth 28275.00 with a monthly
    SYSTEMATIC_WITHDRAWAL plan of 50000.00 due 2026-08-05.

    Returns {"share_class", "account", "plan", "position"}.
    """
    desk = setup_trading_desk(tiers=SINGLE_TIER_BREAKPOINT_TIERS)
    buy_and_settle(desk["account"]["id"], desk["share_class"]["id"], 30000.00)

    plan = create_plan(
        desk["account"]["id"], desk["share_class"]["id"],
        plan_type="SYSTEMATIC_WITHDRAWAL", amount=50000.00, next_run_date=WEDNESDAY,
    )
    set_clock(CLOCK_WEDNESDAY_MORNING)
    return {
        "share_class": desk["share_class"],
        "account": read_account(desk["account"]["id"]),
        "plan": plan,
        "position": only_position(desk["account"]["id"]),
    }


def setup_omnibus_account_with_settled_activity() -> dict:
    """An OMNIBUS/NY account with a settled 30000.00 purchase (2827.500 shares)
    and a settled 100.000 share redemption worth 1000.00, both dated 2026-08-03.

    Returns {"share_class", "account", "purchase", "redemption"}.
    """
    desk = setup_trading_desk(
        tiers=SINGLE_TIER_BREAKPOINT_TIERS,
        state_code="NY",
        account_channel="OMNIBUS",
        registration_type="CORPORATE",
        account_overrides={
            "primary_owner_name": "Omni Broker LLC",
            "dealer_firm_code": "DLR500",
        },
    )
    purchase = buy_and_settle(
        desk["account"]["id"], desk["share_class"]["id"], 30000.00, headers=DEALER
    )
    redemption = redeem_and_settle(
        desk["account"]["id"], desk["share_class"]["id"], 100.000, headers=DEALER
    )
    desk["purchase"] = purchase
    desk["redemption"] = redemption
    return desk


def setup_omnibus_break_identified() -> dict:
    """An OMNIBUS/NY account with a settled 30000.00 purchase dated 2026-08-03
    and a reconciliation reporting 29995.00 of dealer purchases, which
    classifies BREAK_IDENTIFIED with a 5.00 break against a 3.00 tolerance.

    Returns {"share_class", "account", "purchase", "reconciliation"}.
    """
    desk = setup_trading_desk(
        tiers=SINGLE_TIER_BREAKPOINT_TIERS,
        state_code="NY",
        account_channel="OMNIBUS",
        registration_type="CORPORATE",
        account_overrides={
            "primary_owner_name": "Adjust Broker",
            "dealer_firm_code": "DLR600",
        },
    )
    purchase = buy_and_settle(desk["account"]["id"], desk["share_class"]["id"], 30000.00)
    reconciliation = get_success_data(
        api_client.create_omnibus_reconciliation(
            {
                "account_id": desk["account"]["id"],
                "as_of_date": MONDAY,
                "dealer_reported_purchase_amount": 29995.00,
                "dealer_reported_redemption_amount": 0.00,
                "dealer_reported_net_shares": 2827.500,
            },
            OPERATOR,
        )
    )
    desk["purchase"] = purchase
    desk["reconciliation"] = reconciliation
    return desk


def setup_matched_reconciliation_with_unsettled_trade() -> dict:
    """An OMNIBUS/NY account whose only 12000.00 purchase is captured but never
    settled, and a reconciliation that therefore classifies MATCHED.

    Returns {"share_class", "account", "trade", "reconciliation"}.
    """
    desk = setup_trading_desk(
        tiers=SINGLE_TIER_BREAKPOINT_TIERS,
        state_code="NY",
        account_channel="OMNIBUS",
        registration_type="CORPORATE",
        strike_seed_nav=False,
        account_overrides={
            "primary_owner_name": "Quiet Omnibus",
            "dealer_firm_code": "DLR900",
        },
    )
    trade = capture_purchase(desk["account"]["id"], desk["share_class"]["id"], 12000.00)
    reconciliation = get_success_data(
        api_client.create_omnibus_reconciliation(
            {
                "account_id": desk["account"]["id"],
                "as_of_date": MONDAY,
                "dealer_reported_purchase_amount": 0.00,
                "dealer_reported_redemption_amount": 0.00,
                "dealer_reported_net_shares": 0.000,
            },
            OPERATOR,
        )
    )
    desk["trade"] = trade
    desk["reconciliation"] = reconciliation
    return desk


# ================================================= Tier 8: as-of order handling
def setup_pending_as_of_order() -> dict:
    """An as-of order for Monday captured by compliance officer co-1 while the
    clock reads Tuesday 10:00, so it sits in PENDING_AS_OF_APPROVAL.

    Returns {"share_class", "registration", "account", "trade"}.
    """
    base = setup_reference_data(tiers=SINGLE_TIER_BREAKPOINT_TIERS)
    account = open_active_account(primary_owner_name="Ash Asof")
    strike_nav(base["share_class"]["id"], MONDAY, 0.00, finalize=True)
    set_clock("2026-08-04T10:00:00Z")
    trade = get_success_data(
        api_client.create_trade(
            create_purchase_payload(
                account["id"], base["share_class"]["id"], 8000.00, as_of_date=MONDAY
            ),
            make_compliance_headers("co-1"),
        )
    )
    return {
        "share_class": base["share_class"],
        "registration": base["registration"],
        "account": read_account(account["id"]),
        "trade": trade,
    }
