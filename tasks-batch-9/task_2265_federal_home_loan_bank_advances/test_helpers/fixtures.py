"""Composite state builders.

The harness restarts the server before every test, so each test starts against
an empty database and must build every precondition it needs through the API.
This module owns those chains: a member admitted and activated, collateral
pledged and reviewed, an advance requested, approved and funded, a verification
review scored and closed, a shortfall opened, a prepayment quoted and settled.

Builders take the ``api`` client as their first argument and return plain
dictionaries of created rows. They use the lenient success reader internally, so
a setup step that returns any 2xx is accepted and only the assertions inside a
test judge exact status codes.
"""
from dataclasses import dataclass, field

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as _f
from .constants import CLOCK_START
from .test_users import (
    AUDITOR_USER_ID,
    CREDIT_OFFICER_ONE_USER_ID,
    CREDIT_OFFICER_TWO_USER_ID,
    auditor_headers,
    community_manager_headers,
    credit_officer_headers,
    custodian_headers,
    make_treasury_officer_headers,
    system_admin_headers,
)

ADMIN = system_admin_headers()
CREDIT_ONE = credit_officer_headers(CREDIT_OFFICER_ONE_USER_ID)
CREDIT_TWO = credit_officer_headers(CREDIT_OFFICER_TWO_USER_ID)
CUSTODIAN = custodian_headers()
AUDITOR = auditor_headers(AUDITOR_USER_ID)
COMMUNITY = community_manager_headers()


def _ok(response) -> dict:
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Administrative test-driving capabilities
# ---------------------------------------------------------------------------

def pin_clock(api, now: str = CLOCK_START) -> dict:
    """Set the logical clock to a known instant."""
    return _ok(api.set_logical_clock(_f.clock_payload(now), ADMIN))


def set_market_rate(api, market_rate_bps: int) -> dict:
    """Set the global market reinvestment rate."""
    return _ok(api.set_market_rate(_f.market_rate_payload(market_rate_bps), ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creates
# ---------------------------------------------------------------------------

def create_member(api, **overrides) -> dict:
    """Register a member institution. Defaults to Harbor Savings, tier 1."""
    return _ok(api.create_member_bank(_f.member_bank_payload(**overrides), ADMIN))


def read_member(api, member_bank_id: str, headers=None) -> dict:
    return _ok(api.get_member_bank(member_bank_id, headers or CREDIT_ONE))


def member_version(api, member_bank_id: str) -> int:
    """The member's current ``version``, for the two version-bearing writes."""
    return read_member(api, member_bank_id)["version"]


def subscribe_stock(api, member_bank_id: str, amount_cents: int, subscription_type: str = "MEMBERSHIP", headers=None) -> dict:
    return _ok(
        api.create_stock_subscription(
            _f.stock_subscription_payload(
                member_bank_id, amount_cents, subscription_type
            ),
            headers or CREDIT_ONE,
        )
    )


def issue_stock(api, stock_subscription_id: str) -> dict:
    return _ok(api.issue_stock_subscription(stock_subscription_id, CREDIT_ONE))


def subscribe_and_issue(api, member_bank_id: str, amount_cents: int, subscription_type: str = "MEMBERSHIP") -> dict:
    """Buy stock and issue it in one step, so it counts as held."""
    subscription = subscribe_stock(
        api, member_bank_id, amount_cents, subscription_type
    )
    return issue_stock(api, subscription["id"])


def activate_member(api, member_bank_id: str) -> dict:
    return _ok(api.activate_member_bank(member_bank_id, CREDIT_ONE))


def execute_pledge_agreement(api, member_bank_id: str, pledge_mode: str = "BLANKET_LIEN", effective_date: str = CLOCK_START) -> dict:
    return _ok(
        api.execute_pledge_agreement(
            member_bank_id,
            _f.pledge_agreement_payload(pledge_mode, effective_date),
            CREDIT_ONE,
        )
    )


def amend_condition(api, member_bank_id: str, **overrides) -> dict:
    return _ok(
        api.patch_member_bank_condition(
            member_bank_id, _f.condition_payload(**overrides), CREDIT_ONE
        )
    )


def pledge_asset(api, member_bank_id: str, **overrides) -> dict:
    """Pledge a collateral asset as the owning member's treasury officer."""
    return _ok(
        api.create_collateral_asset(
            _f.collateral_asset_payload(member_bank_id, **overrides),
            make_treasury_officer_headers(member_bank_id),
        )
    )


def review_asset(api, collateral_asset_id: str, force_ineligible=None) -> dict:
    payload = {} if force_ineligible is None else {"force_ineligible": force_ineligible}
    return _ok(api.review_asset_eligibility(collateral_asset_id, CREDIT_ONE, payload))


def read_asset(api, collateral_asset_id: str, headers=None) -> dict:
    return _ok(api.get_collateral_asset(collateral_asset_id, headers or CREDIT_ONE))


def amend_documentation(api, collateral_asset_id: str, **overrides) -> dict:
    return _ok(
        api.patch_asset_documentation(
            collateral_asset_id, _f.documentation_patch_payload(**overrides), CUSTODIAN
        )
    )


def create_product(api, **overrides) -> dict:
    return _ok(api.create_advance_product(_f.advance_product_payload(**overrides), ADMIN))


def create_allocation(api, **overrides) -> dict:
    return _ok(
        api.create_community_program_allocation(
            _f.allocation_payload(**overrides), COMMUNITY
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: safekeeping and delivery
# ---------------------------------------------------------------------------

def book_receipt(api, collateral_asset_id: str, **overrides) -> dict:
    return _ok(
        api.create_safekeeping_receipt(
            collateral_asset_id, _f.safekeeping_receipt_payload(**overrides), CUSTODIAN
        )
    )


def confirm_receipt(api, safekeeping_receipt_id: str, outcome: str = "RECEIVED", exception_note=None) -> dict:
    return _ok(
        api.confirm_safekeeping_receipt(
            safekeeping_receipt_id,
            _f.confirm_receipt_payload(outcome, exception_note),
            CUSTODIAN,
        )
    )


def deliver_asset(api, collateral_asset_id: str, delivery_date: str = "2026-08-10T00:00:00Z", return_date: str = "2026-08-20T00:00:00Z") -> dict:
    """Book a delivery, move the clock to the window, and confirm it received.

    Leaves the asset in ``FHLB_SAFEKEEPING`` with a ``RECEIVED`` receipt, which is
    what pushes its ``effective_listing_mode`` to ``DELIVERED``.
    """
    receipt = book_receipt(
        api, collateral_asset_id, delivery_date=delivery_date, return_date=return_date
    )
    pin_clock(api, delivery_date)
    return confirm_receipt(api, receipt["id"], "RECEIVED")


# ---------------------------------------------------------------------------
# Tier 3: the member spine
# ---------------------------------------------------------------------------

@dataclass
class MemberEnv:
    """A member bank plus everything built on top of it."""

    api: object
    member_id: str
    treasury: dict
    assets: dict = field(default_factory=dict)
    subscriptions: dict = field(default_factory=dict)
    advances: dict = field(default_factory=dict)
    reviews: dict = field(default_factory=dict)
    findings: dict = field(default_factory=dict)
    receipts: dict = field(default_factory=dict)
    products: dict = field(default_factory=dict)
    allocations: dict = field(default_factory=dict)

    def refresh(self) -> dict:
        return read_member(self.api, self.member_id)

    @property
    def version(self) -> int:
        return self.refresh()["version"]

    def capacity(self, variant=None, headers=None) -> dict:
        params = None if variant is None else {"variant": variant}
        return _ok(
            self.api.get_borrowing_capacity(
                self.member_id, headers or CREDIT_ONE, params
            )
        )


def applicant_member(api, **overrides) -> MemberEnv:
    """Clock pinned, member registered, nothing else. Status ``APPLICANT``."""
    pin_clock(api)
    member = create_member(api, **overrides)
    return MemberEnv(
        api=api,
        member_id=member["id"],
        treasury=make_treasury_officer_headers(member["id"]),
    )


def active_member(api, membership_stock_cents: int = 9_600_000, **overrides) -> MemberEnv:
    """Registered, membership stock issued, activated. Status ``ACTIVE``."""
    env = applicant_member(api, **overrides)
    subscription = subscribe_stock(api, env.member_id, membership_stock_cents)
    issue_stock(api, subscription["id"])
    env.subscriptions["membership"] = subscription
    activate_member(api, env.member_id)
    return env


def pledging_member(api, pledge_mode: str = "BLANKET_LIEN", membership_stock_cents: int = 9_600_000, **overrides) -> MemberEnv:
    """Active with an executed pledge agreement, ready to pledge collateral."""
    env = active_member(api, membership_stock_cents=membership_stock_cents, **overrides)
    execute_pledge_agreement(api, env.member_id, pledge_mode)
    return env


def member_with_eligible_sf(api, pledge_mode: str = "BLANKET_LIEN", **overrides) -> MemberEnv:
    """The standard spine: one reviewed single-family mortgage, factor 7,800.

    Basis 20,000,000 at 7,800 basis points gives a lendable value of 15,600,000.
    """
    env = pledging_member(api, pledge_mode=pledge_mode, **overrides)
    asset = pledge_asset(api, env.member_id)
    review_asset(api, asset["id"])
    env.assets["sf"] = read_asset(api, asset["id"])
    return env


def add_heloc(api, env: MemberEnv, market_value_cents: int = 1_000_000, unpaid_principal_balance_cents: int = 1_000_000, ltv_bps: int = 7_000, review: bool = True, key: str = "heloc") -> dict:
    """A small HELOC: basis 1,000,000 at 5,000 basis points gives 500,000."""
    asset = pledge_asset(
        api,
        env.member_id,
        asset_class="HELOC",
        market_value_cents=market_value_cents,
        unpaid_principal_balance_cents=unpaid_principal_balance_cents,
        ltv_bps=ltv_bps,
    )
    if review:
        review_asset(api, asset["id"])
    env.assets[key] = read_asset(api, asset["id"])
    return env.assets[key]


def add_cre(api, env: MemberEnv, review: bool = True, key: str = "cre") -> dict:
    """A commercial asset whose appraisal is stale: 5,500 less 500 less 300."""
    asset = pledge_asset(
        api,
        env.member_id,
        asset_class="CRE",
        unpaid_principal_balance_cents=50_000_000,
        market_value_cents=48_000_000,
        ltv_bps=8_200,
        appraisal_date="2024-01-15T00:00:00Z",
    )
    if review:
        review_asset(api, asset["id"])
    env.assets[key] = read_asset(api, asset["id"])
    return env.assets[key]


# ---------------------------------------------------------------------------
# Tier 4: advances
# ---------------------------------------------------------------------------

def request_advance(api, env: MemberEnv, advance_product_id: str, expected_member_bank_version=None, **overrides) -> dict:
    """Request an advance, reading the member's live version unless one is given."""
    version = (
        env.version if expected_member_bank_version is None else expected_member_bank_version
    )
    return _ok(
        api.create_advance(
            _f.advance_payload(
                env.member_id, advance_product_id, version, **overrides
            ),
            env.treasury,
        )
    )


def approve_advance(api, advance_id: str, headers=None) -> dict:
    """Approve as credit officer one, leaving officer two free to fund."""
    return _ok(api.approve_advance(advance_id, headers or CREDIT_ONE))


def fund_advance(api, advance_id: str, headers=None) -> dict:
    """Fund as credit officer two, satisfying segregation of duties."""
    return _ok(api.fund_advance(advance_id, headers or CREDIT_TWO))


def read_advance(api, advance_id: str, headers=None) -> dict:
    return _ok(api.get_advance(advance_id, headers or CREDIT_ONE))


def funded_advance(api, env: MemberEnv, advance_product_id: str, **overrides) -> dict:
    """Request, approve and fund an advance in one call."""
    advance = request_advance(api, env, advance_product_id, **overrides)
    approve_advance(api, advance["id"])
    return fund_advance(api, advance["id"])


def approved_advance(api, env: MemberEnv, advance_product_id: str, **overrides) -> dict:
    """Request and approve an advance, stopping short of funding."""
    advance = request_advance(api, env, advance_product_id, **overrides)
    return approve_advance(api, advance["id"])


def repay_advance(api, advance_id: str) -> dict:
    return _ok(api.repay_advance(advance_id, CREDIT_ONE))


def quote_prepayment(api, env: MemberEnv, advance_id: str, prepay_amount_cents: int, prepay_kind: str = "FULL") -> dict:
    return _ok(
        api.create_prepayment_quote(
            advance_id,
            _f.prepayment_quote_payload(prepay_amount_cents, prepay_kind),
            env.treasury,
        )
    )


def settle_prepayment(api, prepayment_event_id: str) -> dict:
    return _ok(api.settle_prepayment_event(prepayment_event_id, CREDIT_ONE))


# ---------------------------------------------------------------------------
# Tier 5: verification reviews
# ---------------------------------------------------------------------------

def schedule_review(api, env: MemberEnv, **overrides) -> dict:
    return _ok(
        api.create_verification_review(
            _f.verification_review_payload(env.member_id, **overrides), AUDITOR
        )
    )


def begin_field_work(api, review_id: str) -> dict:
    return _ok(api.begin_field_work(review_id, AUDITOR))


def raise_finding(api, review_id: str, collateral_asset_id: str, severity: str = "MAJOR", finding_type: str = "MISSING_NOTE", headers=None) -> dict:
    return _ok(
        api.create_review_finding(
            review_id,
            _f.review_finding_payload(collateral_asset_id, finding_type, severity),
            headers or AUDITOR,
        )
    )


def issue_findings(api, review_id: str) -> dict:
    return _ok(api.issue_findings(review_id, AUDITOR))


def retest_review(api, review_id: str) -> dict:
    return _ok(api.retest_review(review_id, AUDITOR))


def close_review(api, review_id: str) -> dict:
    return _ok(api.close_review(review_id, AUDITOR))


def remediate_finding(api, env: MemberEnv, finding_id: str) -> dict:
    return _ok(api.remediate_review_finding(finding_id, env.treasury))


def waive_finding(api, finding_id: str, headers=None) -> dict:
    """Waive as credit officer one, whose id differs from the auditor's."""
    return _ok(api.waive_review_finding(finding_id, headers or CREDIT_ONE))


def read_review(api, review_id: str, headers=None) -> dict:
    return _ok(api.get_verification_review(review_id, headers or CREDIT_ONE))


def review_in_field_work(api, env: MemberEnv, **overrides) -> dict:
    """Schedule a review and begin its field work."""
    review = schedule_review(api, env, **overrides)
    begin_field_work(api, review["id"])
    env.reviews["current"] = review
    return review


def review_with_findings_issued(api, env: MemberEnv, collateral_asset_id: str, severities=("MAJOR",), **overrides) -> tuple:
    """Field work with the given findings recorded, then issued.

    Returns the review row and the list of finding rows.
    """
    review = review_in_field_work(api, env, **overrides)
    findings = [
        raise_finding(api, review["id"], collateral_asset_id, severity)
        for severity in severities
    ]
    issued = issue_findings(api, review["id"])
    return issued, findings


def closed_review(api, env: MemberEnv, collateral_asset_id: str, severities=("MAJOR",), **overrides) -> tuple:
    """Run a review all the way through its close cascade."""
    review, findings = review_with_findings_issued(
        api, env, collateral_asset_id, severities, **overrides
    )
    return close_review(api, review["id"]), findings


# ---------------------------------------------------------------------------
# Tier 6: postures, shortfalls and terminal states
# ---------------------------------------------------------------------------

def member_with_failed_review(api, env: MemberEnv, collateral_asset_id: str, sample_size: int = 40, **overrides) -> dict:
    """Close a review at a 10.00 percent exception rate: outcome ``FAIL``.

    Four ``MAJOR`` findings over a sample of 40 score 4.0, which is exactly
    10.00 percent, selecting the 1,500 basis point haircut band.
    """
    return closed_review(
        api,
        env,
        collateral_asset_id,
        severities=("MAJOR", "MAJOR", "MAJOR", "MAJOR"),
        sample_size=sample_size,
        **overrides,
    )[0]


def freeze_member_via_documentation_exception(api, env: MemberEnv, collateral_asset_id: str) -> dict:
    """Amend an asset's documentation, which zeroes its lendable value.

    With a funded advance outstanding this drives certified capacity negative,
    which freezes the posture and opens a shortfall.
    """
    amend_documentation(api, collateral_asset_id, documentation_status="EXCEPTION")
    return env.refresh()


def escalate_shortfall(api, member_bank_id: str) -> dict:
    return _ok(api.escalate_shortfall(member_bank_id, CREDIT_ONE))


def substitute_asset(api, env: MemberEnv, collateral_asset_id: str, expected_member_bank_version=None, **overrides) -> dict:
    """Substitute a pledged asset; the replacement comes back in the response."""
    version = (
        env.version if expected_member_bank_version is None else expected_member_bank_version
    )
    return _ok(
        api.substitute_collateral_asset(
            collateral_asset_id,
            _f.substitution_payload(version, **overrides),
            env.treasury,
        )
    )


def second_member(api, name: str = "Cascade Mutual", charter_type: str = "COMMERCIAL_BANK", total_assets_cents: int = 5_000_000_000, credit_rating_tier: int = 2, membership_stock_cents: int = 6_000_000, activate: bool = True) -> MemberEnv:
    """A second institution, used by the member-scope and mismatch translations.

    Twelve basis points of 5,000,000,000 cents is 6,000,000 cents of membership
    stock.
    """
    member = create_member(
        api,
        name=name,
        charter_type=charter_type,
        total_assets_cents=total_assets_cents,
        credit_rating_tier=credit_rating_tier,
    )
    env = MemberEnv(
        api=api,
        member_id=member["id"],
        treasury=make_treasury_officer_headers(member["id"]),
    )
    if activate:
        subscription = subscribe_stock(api, env.member_id, membership_stock_cents)
        issue_stock(api, subscription["id"])
        env.subscriptions["membership"] = subscription
        activate_member(api, env.member_id)
    return env


# ---------------------------------------------------------------------------
# pytest fixtures over the most reused chains
# ---------------------------------------------------------------------------

@pytest.fixture
def clock(api):
    """The logical clock pinned to its documented start instant."""
    pin_clock(api)
    return CLOCK_START


@pytest.fixture
def applicant(api):
    return applicant_member(api)


@pytest.fixture
def active(api):
    return active_member(api)


@pytest.fixture
def pledging(api):
    return pledging_member(api)


@pytest.fixture
def harbor(api):
    """Harbor Savings with one eligible single-family mortgage pledged."""
    return member_with_eligible_sf(api)


@pytest.fixture
def standard_product(api):
    """The reference fixed-term product used across the advance translations."""
    return create_product(api)
