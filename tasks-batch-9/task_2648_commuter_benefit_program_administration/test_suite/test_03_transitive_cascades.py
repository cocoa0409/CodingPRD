"""Four-level transitive cascades: window locking and substantiation denial.

Both chains in this module run four hops deep, and in both of them the final hop
is caused by the hop above it rather than by the request the caller made.  Every
test below asserts a specific hop of one chain -- the row the request named, the
row two entities removed from it, and the money and counters in between -- so a
partial implementation that stops after the first hop cannot pass.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import PROGRAM_ADMIN, factories as f, fixtures as fx
from test_helpers.api_errors import ERROR_HTTP_STATUS  # noqa: F401  (installs status map)
from test_helpers.assertions import (
    assert_account_conservation,
    assert_election_axes,
    assert_exclusion_split,
    assert_ledger_matches_account,
    assert_ledger_sequence,
)
from test_helpers.constants import DEFAULT_CLOCK, REGION_NYC, REGION_SFO
from test_helpers.test_users import make_compliance_reviewer_headers

# --- Cascade A: the pre-tax figures that drive an employer past its program cap
CAP_BREACH_PRETAX_CENTS = 30000
CAP_BREACH_PROGRAM_CAP_CENTS = 25000

# --- Cascade B: the July contribution, the swipe and the August pre-tax request
JULY_PRETAX_CENTS = 5000
AUGUST_PRETAX_CENTS = 4000
SWIPE_CENTS = 3000
DENYING_REVIEWER_ID = "reviewer-diaz"


def _build_cap_breach_scenario(api, program_cap_cents=CAP_BREACH_PROGRAM_CAP_CENTS):
    """An ACTIVE San Francisco program carrying exactly one PENDING election.

    The employer's group limit and the category's monthly sub-limit are both wide
    enough that the exclusion split does not clip the 30000-cent pre-tax request,
    so the whole request lands on the employer's committed pre-tax total when the
    window locks.  ``program_cap_cents`` decides whether that total breaches the
    cap or merely reaches it.
    """
    base = fx.make_program_with_participant(
        api,
        region_code=REGION_SFO,
        employer_overrides={
            "legal_name": "Bay Area Cap Test",
            "transit_group_limit_cents": 30000,
            "parking_group_limit_cents": 30000,
            "pretax_ratio_cap_pct": 100,
            "spill_policy": "SPILL_TO_POSTTAX",
            "program_cap_cents": program_cap_cents,
        },
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
        window_overrides={
            "benefit_month": "2026-08",
            "opens_at": "2026-07-01T00:00:00Z",
            "cutoff_at": "2026-08-20T00:00:00Z",
        },
    )
    base["election"] = fx.make_election(
        api,
        base["employee"]["id"],
        base["window"]["id"],
        base["category"]["id"],
        base["account"]["id"],
        pretax_amount_cents=CAP_BREACH_PRETAX_CENTS,
        posttax_amount_cents=0,
    )
    return base


def test_01_locking_window_reprices_pending_election_into_funded(api):
    """PRD 3.4: "every election in the window whose `funding_status` is `PENDING`
    is re-priced under the funded-basis variant, rewriting `excluded_amount_cents`,
    `posttax_spill_cents` and `posttax_effective_cents` and setting
    `exclusion_basis` to `FUNDED_BASIS`"
    PRD 3.4: "Each re-priced election then lands in one of two postures:
    `PENDING → HELD` when the electing employee's `substantiation_hold` is true,
    and `PENDING → FUNDED` otherwise."

    Design: Difficulty/transitive_cascade/window_lock_cascades_window_to_election_to_account_to_employer_suspension
    """
    scenario = _build_cap_breach_scenario(api)
    employer_before = fx.read_employer(api, scenario["employer"]["id"])
    assert employer_before["program_status"] == "ACTIVE"
    assert employer_before["total_pretax_committed_cents"] == 0
    assert scenario["election"]["funding_status"] == "PENDING"

    window = validate_success(
        api.lock_election_window(scenario["window"]["id"], PROGRAM_ADMIN)
    )
    assert window["status"] == "LOCKED", "hop 1 must move the window OPEN -> LOCKED"
    assert window["locked_at"] is not None, "locked_at is stamped at hop 1"
    assert window["election_count"] == 1

    election = fx.read_election(api, scenario["election"]["id"])
    assert_election_axes(election, "FUNDED", "NOT_REQUIRED")
    assert_exclusion_split(
        election,
        excluded_amount_cents=CAP_BREACH_PRETAX_CENTS,
        posttax_spill_cents=0,
        total_amount_cents=CAP_BREACH_PRETAX_CENTS,
        exclusion_basis="FUNDED_BASIS",
    )


def test_02_funded_election_credits_its_benefit_account_with_one_contribution(api):
    """PRD 3.4: "One ledger entry is appended to that election's benefit account
    with `entry_type` `CONTRIBUTION`, a positive `amount_cents` equal to the
    election's `total_amount_cents`, `source_entity` `Election` and `source_id` the
    election's identifier; the account's `contributed_cents` increases by that same
    `total_amount_cents`, `available_balance_cents` is recomputed against the
    conservation identities, `ledger_entry_count` is incremented, and
    `BenefitAccount.version` advances by 1."

    Design: Difficulty/transitive_cascade/window_lock_cascades_window_to_election_to_account_to_employer_suspension
    """
    scenario = _build_cap_breach_scenario(api)
    account_before = fx.read_account(api, scenario["account"]["id"])
    assert account_before["contributed_cents"] == 0
    assert account_before["available_balance_cents"] == 0
    assert account_before["ledger_entry_count"] == 0

    validate_success(api.lock_election_window(scenario["window"]["id"], PROGRAM_ADMIN))

    account = fx.read_account(api, scenario["account"]["id"])
    assert account["contributed_cents"] == CAP_BREACH_PRETAX_CENTS
    assert account["available_balance_cents"] == CAP_BREACH_PRETAX_CENTS
    assert account["ledger_entry_count"] == 1
    assert account["version"] == account_before["version"] + 1, (
        "hop 3 must advance BenefitAccount.version by exactly 1"
    )
    assert_account_conservation(account)

    entries = fx.read_ledger(api, scenario["account"]["id"])
    assert_ledger_sequence(
        entries, [("CONTRIBUTION", CAP_BREACH_PRETAX_CENTS, CAP_BREACH_PRETAX_CENTS)]
    )
    assert entries[0]["benefit_account_id"] == scenario["account"]["id"]
    assert entries[0]["source_entity"] == "Election"
    assert entries[0]["source_id"] == scenario["election"]["id"]
    assert_ledger_matches_account(account, entries)


def test_03_account_credit_pushes_committed_total_past_cap_and_suspends_program(api):
    """PRD 3.4: "The employer's `total_pretax_committed_cents` is recomputed as the
    sum of `excluded_amount_cents` over every election whose window belongs to this
    employer and whose `funding_status` is exactly `FUNDED`."
    PRD 3.4: "If the recomputed total is **strictly greater** than the employer's
    `program_cap_cents`, the employer is driven `ACTIVE → SUSPENDED` and
    `Employer.version` advances by 1."

    Design: Difficulty/transitive_cascade/window_lock_cascades_window_to_election_to_account_to_employer_suspension
    """
    scenario = _build_cap_breach_scenario(api)
    employer_before = fx.read_employer(api, scenario["employer"]["id"])
    assert employer_before["program_status"] == "ACTIVE"
    assert employer_before["program_cap_cents"] == CAP_BREACH_PROGRAM_CAP_CENTS

    validate_success(api.lock_election_window(scenario["window"]["id"], PROGRAM_ADMIN))

    employer = fx.read_employer(api, scenario["employer"]["id"])
    assert employer["total_pretax_committed_cents"] == CAP_BREACH_PRETAX_CENTS
    assert employer["program_status"] == "SUSPENDED", (
        "hop 4 must suspend the program once the committed total breaches the cap"
    )
    assert employer["version"] == employer_before["version"] + 1, (
        "the suspended employer row must advance version by exactly 1"
    )


def test_04_committed_total_equal_to_program_cap_leaves_program_active(api):
    """PRD 3.4: "A committed total exactly equal to `program_cap_cents` does
    **not** suspend the program; only a breach does."
    PRD 3.4: "The employer's `total_pretax_committed_cents` is recomputed as the
    sum of `excluded_amount_cents` over every election whose window belongs to this
    employer and whose `funding_status` is exactly `FUNDED`."

    Design: Difficulty/transitive_cascade/window_lock_cascades_window_to_election_to_account_to_employer_suspension
    """
    scenario = _build_cap_breach_scenario(
        api, program_cap_cents=CAP_BREACH_PRETAX_CENTS
    )
    validate_success(api.lock_election_window(scenario["window"]["id"], PROGRAM_ADMIN))

    election = fx.read_election(api, scenario["election"]["id"])
    assert election["funding_status"] == "FUNDED"

    employer = fx.read_employer(api, scenario["employer"]["id"])
    assert employer["total_pretax_committed_cents"] == CAP_BREACH_PRETAX_CENTS
    assert employer["program_status"] == "ACTIVE", (
        "reaching the cap exactly is not a breach, so hop 4 must not suspend"
    )

    account = fx.read_account(api, scenario["account"]["id"])
    assert account["available_balance_cents"] == CAP_BREACH_PRETAX_CENTS
    assert_account_conservation(account)


def _build_receivable_scenario(api):
    """A Manhattan commuter with a FUNDED July election, a PENDING August election
    and a documented July swipe awaiting review.

    July is collected and locked while the clock sits at 2026-07-01, so the account
    holds a real 5000-cent contribution; the clock then returns to its default
    instant and the adjacent August window collects a second, still PENDING
    election that the swipe never references.  The 3000-cent swipe is above the
    auto-substantiation ceiling, so it lands in `PENDING_DOCS` with its spend
    already posted.
    """
    fx.set_clock(api, "2026-07-01T00:00:00Z")
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000}
        ],
        legal_name="Manhattan Commute Co",
        region_code=REGION_NYC,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        pretax_ratio_cap_pct=100,
        spill_policy="SPILL_TO_POSTTAX",
        program_cap_cents=5000000,
    )
    employer = built["employer"]
    category = built["categories"][0]
    enrolled = fx.make_enrolled_employee(
        api,
        employer["id"],
        category["id"],
        PROGRAM_ADMIN,
        external_ref="NYC-SUB-1",
        work_region_code=REGION_NYC,
        payroll_cycle="SEMI_MONTHLY",
        hire_date="2026-01-15T00:00:00Z",
    )
    employee = enrolled["employee"]
    account = enrolled["account"]

    july_window = fx.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-07",
        opens_at="2026-06-01T00:00:00Z",
        cutoff_at="2026-07-20T00:00:00Z",
    )
    july_election = fx.make_election(
        api,
        employee["id"],
        july_window["id"],
        category["id"],
        account["id"],
        pretax_amount_cents=JULY_PRETAX_CENTS,
        posttax_amount_cents=0,
    )
    get_success_data(api.lock_election_window(july_window["id"], PROGRAM_ADMIN))

    fx.set_clock(api, DEFAULT_CLOCK)
    august_window = fx.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-08",
        opens_at="2026-07-20T00:00:00Z",
        cutoff_at="2026-08-20T00:00:00Z",
    )
    august_election = fx.make_election(
        api,
        employee["id"],
        august_window["id"],
        category["id"],
        account["id"],
        pretax_amount_cents=AUGUST_PRETAX_CENTS,
        posttax_amount_cents=0,
    )
    transaction = get_success_data(
        api.create_card_transaction(
            f.card_transaction_payload(
                july_election["id"],
                amount_cents=SWIPE_CENTS,
                merchant_category_code=4111,
                merchant_name="MTA SUBWAY VENDING",
                transaction_at="2026-07-15T09:12:00Z",
            ),
            PROGRAM_ADMIN,
        )
    )
    return {
        "employer": employer,
        "category": category,
        "employee": employee,
        "account": account,
        "july_window": july_window,
        "july_election": july_election,
        "august_window": august_window,
        "august_election": august_election,
        "transaction": transaction,
    }


def test_05_denying_substantiation_voids_the_swipe_and_its_posted_spend(api):
    """PRD 3.7: "**The first level** sets the transaction's
    `substantiation_status` to `INELIGIBLE`, records the acting `X-User-ID` as
    `denied_by_user_id`, zeroes `posted_spend_cents`, and advances
    `CardTransaction.version` by 1."

    Design: Difficulty/transitive_cascade/deny_substantiation_cascades_transaction_to_account_to_employee_to_pending_election_hold
    """
    scenario = _build_receivable_scenario(api)
    transaction_before = scenario["transaction"]
    assert transaction_before["substantiation_status"] == "PENDING_DOCS"
    assert transaction_before["posted_spend_cents"] == SWIPE_CENTS

    denied = validate_success(
        api.deny_substantiation(
            transaction_before["id"],
            {"reason": "no commuter receipt supplied for the audited swipe"},
            make_compliance_reviewer_headers(DENYING_REVIEWER_ID),
        )
    )
    assert denied["substantiation_status"] == "INELIGIBLE"
    assert denied["posted_spend_cents"] == 0
    assert denied["denied_by_user_id"] == DENYING_REVIEWER_ID
    assert denied["version"] == transaction_before["version"] + 1
    assert denied["amount_cents"] == SWIPE_CENTS, (
        "the settled swipe amount itself is never rewritten by a denial"
    )


def test_06_denial_credits_a_spend_reversal_back_into_the_benefit_account(api):
    """PRD 3.7: "one ledger entry is appended to the transaction's benefit account
    with `entry_type` `SPEND_REVERSAL` and a **positive** `amount_cents` equal to
    the transaction's `amount_cents`, with `source_entity` `CardTransaction` and
    `source_id` the transaction's identifier; the account's `spent_cents` decreases
    by that amount, `available_balance_cents` is recomputed, `ledger_entry_count`
    is incremented and `BenefitAccount.version` advances by 1."

    Design: Difficulty/transitive_cascade/deny_substantiation_cascades_transaction_to_account_to_employee_to_pending_election_hold
    """
    scenario = _build_receivable_scenario(api)
    account_before = fx.read_account(api, scenario["account"]["id"])
    assert account_before["spent_cents"] == SWIPE_CENTS
    assert account_before["available_balance_cents"] == JULY_PRETAX_CENTS - SWIPE_CENTS
    assert account_before["ledger_entry_count"] == 2

    validate_success(
        api.deny_substantiation(
            scenario["transaction"]["id"],
            {"reason": "no commuter receipt supplied for the audited swipe"},
            make_compliance_reviewer_headers(DENYING_REVIEWER_ID),
        )
    )

    account = fx.read_account(api, scenario["account"]["id"])
    assert account["spent_cents"] == 0
    assert account["available_balance_cents"] == JULY_PRETAX_CENTS
    assert account["ledger_entry_count"] == 3
    assert account["version"] == account_before["version"] + 1
    assert_account_conservation(account)

    entries = fx.read_ledger(api, scenario["account"]["id"])
    assert_ledger_sequence(
        entries,
        [
            ("CONTRIBUTION", JULY_PRETAX_CENTS, JULY_PRETAX_CENTS),
            ("SPEND", -SWIPE_CENTS, JULY_PRETAX_CENTS - SWIPE_CENTS),
            ("SPEND_REVERSAL", SWIPE_CENTS, JULY_PRETAX_CENTS),
        ],
    )
    assert entries[2]["source_entity"] == "CardTransaction"
    assert entries[2]["source_id"] == scenario["transaction"]["id"]
    assert_ledger_matches_account(account, entries)


def test_07_receivable_hold_freezes_the_employees_unrelated_pending_election(api):
    """PRD 3.7: "so `repayment_due_cents` on the employee increases by the credited
    amount, `substantiation_hold` is set to true exactly when `repayment_due_cents`
    is greater than zero, and `Employee.version` advances by 1."
    PRD 3.7: "**The fourth level is caused by the hold flag**: every election of
    that employee whose `funding_status` is `PENDING` is driven `PENDING → HELD`."
    PRD 3.7: "A held election keeps its `excluded_amount_cents` and
    `posttax_effective_cents` exactly as they stand and its benefit account is not
    touched; only `funding_status` changes, and `Election.version` advances by 1."

    Design: Difficulty/transitive_cascade/deny_substantiation_cascades_transaction_to_account_to_employee_to_pending_election_hold
    """
    scenario = _build_receivable_scenario(api)
    employee_before = fx.read_employee(api, scenario["employee"]["id"])
    assert employee_before["repayment_due_cents"] == 0
    assert employee_before["substantiation_hold"] is False
    august_before = fx.read_election(api, scenario["august_election"]["id"])
    assert august_before["funding_status"] == "PENDING"
    assert august_before["excluded_amount_cents"] == AUGUST_PRETAX_CENTS

    validate_success(
        api.deny_substantiation(
            scenario["transaction"]["id"],
            {"reason": "no commuter receipt supplied for the audited swipe"},
            make_compliance_reviewer_headers(DENYING_REVIEWER_ID),
        )
    )

    employee = fx.read_employee(api, scenario["employee"]["id"])
    assert employee["repayment_due_cents"] == SWIPE_CENTS
    assert employee["substantiation_hold"] is True
    assert employee["version"] == employee_before["version"] + 1

    august = fx.read_election(api, scenario["august_election"]["id"])
    assert august["funding_status"] == "HELD", (
        "hop 4 must freeze the employee's other PENDING election, "
        "which the denied swipe never referenced"
    )
    assert august["excluded_amount_cents"] == august_before["excluded_amount_cents"]
    assert august["posttax_effective_cents"] == august_before["posttax_effective_cents"]
    assert august["version"] == august_before["version"] + 1

    july = fx.read_election(api, scenario["july_election"]["id"])
    assert july["funding_status"] == "FUNDED", (
        "only PENDING elections are driven to HELD by the hold flag"
    )

    account = fx.read_account(api, scenario["account"]["id"])
    assert account["ledger_entry_count"] == 3, (
        "the hold hop moves no money, so no fourth ledger entry may appear"
    )
    assert_account_conservation(account)
