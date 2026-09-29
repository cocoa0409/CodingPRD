"""Composite state builders for the commuter benefit service.

Every test runs against a freshly restarted, empty database, so all preconditions
have to be built from scratch through the documented endpoints.  These builders
do that and nothing else: they use the lenient ``get_success_data`` so a broken
precondition reads as a setup failure rather than as an assertion failure inside
the test under audit.

The builders are organised in five tiers:

1. State progression  -- an employer walked to a given ``program_status``.
2. Entity hierarchy   -- employer / category / employee / account / window chains.
3. Lifecycle shortcuts -- funded elections, sealed and released procurement.
4. Accumulation targeting -- rosters and batches sized to sit on a threshold.
5. Finalization / terminal -- month close, payroll transmit, terminal media.

Identity threading is mandatory: any call whose actor identity is recorded or
compared takes an explicit ``*_user_id`` so the caller controls it.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import DEFAULT_CLOCK, REGION_AUS
from .test_users import (
    PROGRAM_ADMIN,
    make_compliance_reviewer_headers,
    make_employee_headers,
    make_order_desk_headers,
    make_payroll_processor_headers,
    make_program_admin_headers,
)


# =============================================================================
# Tier 0: raw single-step helpers
# =============================================================================
def set_clock(api, instant: str, admin_headers: Optional[Dict] = None) -> None:
    """Move the logical clock.  Mutates no entity and fires no cascade."""
    get_success_data(api.set_clock(instant, admin_headers or PROGRAM_ADMIN))


def reset_clock(api, admin_headers: Optional[Dict] = None) -> None:
    set_clock(api, DEFAULT_CLOCK, admin_headers)


# =============================================================================
# Tier 1: state progression -- employer programs
# =============================================================================
def make_draft_employer(api, headers: Optional[Dict] = None, **overrides) -> Dict[str, Any]:
    """An employer program sitting in DRAFT."""
    headers = headers or PROGRAM_ADMIN
    return get_success_data(api.create_employer(f.employer_payload(**overrides), headers))


def make_active_employer(
    api, headers: Optional[Dict] = None, categories: Optional[List[Dict]] = None, **overrides
) -> Dict[str, Any]:
    """An employer walked DRAFT -> ACTIVE, with its categories declared first.

    ``categories`` is a list of keyword dicts forwarded to the category factory.
    Returns ``{"employer": ..., "categories": [...]}``.
    """
    headers = headers or PROGRAM_ADMIN
    employer = make_draft_employer(api, headers, **overrides)
    made: List[Dict[str, Any]] = []
    for spec in categories or [{}]:
        made.append(
            get_success_data(
                api.create_benefit_category(
                    f.benefit_category_payload(employer["id"], **spec), headers
                )
            )
        )
    employer = get_success_data(api.activate_employer(employer["id"], headers))
    return {"employer": employer, "categories": made}


# =============================================================================
# Tier 2: entity hierarchy -- employer / category / employee / account / window
# =============================================================================
def make_employee(api, employer_id: str, headers: Optional[Dict] = None, **overrides) -> Dict[str, Any]:
    headers = headers or PROGRAM_ADMIN
    return get_success_data(
        api.create_employee(f.employee_payload(employer_id, **overrides), headers)
    )


def make_benefit_account(
    api,
    employee_id: str,
    benefit_category_id: str,
    headers: Optional[Dict] = None,
    **overrides,
) -> Dict[str, Any]:
    headers = headers or PROGRAM_ADMIN
    return get_success_data(
        api.create_benefit_account(
            f.benefit_account_payload(employee_id, benefit_category_id, **overrides),
            headers,
        )
    )


def make_open_window(api, employer_id: str, headers: Optional[Dict] = None, **overrides) -> Dict[str, Any]:
    """A window created SCHEDULED and then opened."""
    headers = headers or PROGRAM_ADMIN
    window = get_success_data(
        api.create_election_window(f.election_window_payload(employer_id, **overrides), headers)
    )
    return get_success_data(api.open_election_window(window["id"], headers))


def make_scheduled_window(
    api, employer_id: str, headers: Optional[Dict] = None, **overrides
) -> Dict[str, Any]:
    headers = headers or PROGRAM_ADMIN
    return get_success_data(
        api.create_election_window(f.election_window_payload(employer_id, **overrides), headers)
    )


def make_transit_media(
    api, desk_user_id: str = "desk-catalog", **overrides
) -> Dict[str, Any]:
    """A catalogue product.  The OrderDesk operator id is explicit."""
    return get_success_data(
        api.create_transit_media(
            f.transit_media_payload(**overrides), make_order_desk_headers(desk_user_id)
        )
    )


def make_enrolled_employee(
    api,
    employer_id: str,
    benefit_category_id: str,
    headers: Optional[Dict] = None,
    account_overrides: Optional[Dict] = None,
    **employee_overrides,
) -> Dict[str, Any]:
    """An employee plus the benefit account that anchors their elections.

    Returns ``{"employee": ..., "account": ...}``.
    """
    headers = headers or PROGRAM_ADMIN
    employee = make_employee(api, employer_id, headers, **employee_overrides)
    account = make_benefit_account(
        api, employee["id"], benefit_category_id, headers, **(account_overrides or {})
    )
    return {"employee": employee, "account": account}


def make_program_with_participant(
    api,
    region_code: str = REGION_AUS,
    employer_overrides: Optional[Dict] = None,
    category_overrides: Optional[Dict] = None,
    account_overrides: Optional[Dict] = None,
    window_overrides: Optional[Dict] = None,
    open_window: bool = True,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """The workhorse chain: ACTIVE employer, one category, one employee with an
    account, and one election window (OPEN by default).

    Returns ``{"employer", "category", "employee", "account", "window"}``.
    """
    headers = headers or PROGRAM_ADMIN
    built = make_active_employer(
        api,
        headers,
        categories=[category_overrides or {}],
        region_code=region_code,
        **(employer_overrides or {}),
    )
    employer = built["employer"]
    category = built["categories"][0]
    enrolled = make_enrolled_employee(
        api,
        employer["id"],
        category["id"],
        headers,
        account_overrides=account_overrides,
        work_region_code=region_code,
    )
    if open_window:
        window = make_open_window(api, employer["id"], headers, **(window_overrides or {}))
    else:
        window = make_scheduled_window(
            api, employer["id"], headers, **(window_overrides or {})
        )
    return {
        "employer": employer,
        "category": category,
        "employee": enrolled["employee"],
        "account": enrolled["account"],
        "window": window,
    }


# =============================================================================
# Tier 3: lifecycle shortcuts -- elections and procurement
# =============================================================================
def current_account_version(api, account_id: str, headers: Optional[Dict] = None) -> int:
    headers = headers or PROGRAM_ADMIN
    return get_success_data(api.get_benefit_account(account_id, headers))["version"]


def current_election_version(api, election_id: str, headers: Optional[Dict] = None) -> int:
    headers = headers or PROGRAM_ADMIN
    return get_success_data(api.get_election(election_id, headers))["version"]


def make_election(
    api,
    employee_id: str,
    window_id: str,
    category_id: str,
    account_id: str,
    headers: Optional[Dict] = None,
    **overrides,
) -> Dict[str, Any]:
    """A PENDING election filed with a freshly read account version."""
    headers = headers or PROGRAM_ADMIN
    version = current_account_version(api, account_id, PROGRAM_ADMIN)
    return get_success_data(
        api.create_election(
            f.election_payload(
                employee_id, window_id, category_id, version, **overrides
            ),
            headers,
        )
    )


def make_funded_election(
    api,
    region_code: str = REGION_AUS,
    pretax_amount_cents: int = 10000,
    employer_overrides: Optional[Dict] = None,
    category_overrides: Optional[Dict] = None,
    account_overrides: Optional[Dict] = None,
    window_overrides: Optional[Dict] = None,
    election_overrides: Optional[Dict] = None,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """A FUNDED election: the window is locked, so the funding cascade has run.

    Returns ``{"employer", "category", "employee", "account", "window",
    "election"}`` with the window and election re-read after the lock.
    """
    headers = headers or PROGRAM_ADMIN
    base = make_program_with_participant(
        api,
        region_code=region_code,
        employer_overrides=employer_overrides,
        category_overrides=category_overrides,
        account_overrides=account_overrides,
        window_overrides=window_overrides,
        headers=headers,
    )
    election = make_election(
        api,
        base["employee"]["id"],
        base["window"]["id"],
        base["category"]["id"],
        base["account"]["id"],
        headers,
        pretax_amount_cents=pretax_amount_cents,
        **(election_overrides or {}),
    )
    window = get_success_data(api.lock_election_window(base["window"]["id"], headers))
    base["window"] = window
    base["election"] = get_success_data(api.get_election(election["id"], headers))
    base["account"] = get_success_data(
        api.get_benefit_account(base["account"]["id"], headers)
    )
    return base


def make_open_batch(
    api, window_id: str, region_code: str = REGION_AUS, desk_user_id: str = "desk-ops"
) -> Dict[str, Any]:
    return get_success_data(
        api.create_order_batch(
            f.order_batch_payload(window_id, region_code),
            make_order_desk_headers(desk_user_id),
        )
    )


def make_media_order(
    api,
    election_id: str,
    transit_media_id: str,
    order_batch_id: str,
    desk_user_id: str = "desk-ops",
    **overrides,
) -> Dict[str, Any]:
    """A PENDING media line filed with a freshly read election version."""
    version = current_election_version(api, election_id)
    return get_success_data(
        api.create_media_order(
            f.media_order_payload(
                election_id, transit_media_id, order_batch_id, version, **overrides
            ),
            make_order_desk_headers(desk_user_id),
        )
    )


def make_procurement_chain(
    api,
    region_code: str = REGION_AUS,
    media_quantity: int = 1,
    pretax_amount_cents: int = 6000,
    unit_price_cents: int = 6000,
    seal_user_id: str = "desk-sealer",
    release_user_id: str = "desk-releaser",
    stop_after: str = "released",
    employer_overrides: Optional[Dict] = None,
    category_overrides: Optional[Dict] = None,
    account_overrides: Optional[Dict] = None,
    window_overrides: Optional[Dict] = None,
    media_overrides: Optional[Dict] = None,
    coverage_start_at: str = "2026-08-01T00:00:00Z",
    coverage_end_at: str = "2026-08-31T00:00:00Z",
) -> Dict[str, Any]:
    """The full media procurement chain against one PENDING election.

    ``stop_after`` is one of ``ordered``, ``sealed``, ``released``, ``shipped``,
    ``delivered`` and decides how far the chain is walked.  The sealing and
    releasing operator ids are distinct by default because releasing a batch
    requires an operator different from the one who sealed it.

    Returns ``{"employer", "category", "employee", "account", "window", "media",
    "election", "batch", "order"}``.
    """
    base = make_program_with_participant(
        api,
        region_code=region_code,
        employer_overrides=employer_overrides,
        category_overrides=category_overrides,
        account_overrides=account_overrides,
        window_overrides=window_overrides,
    )
    media = make_transit_media(
        api,
        region_code=region_code,
        eligible_category_type=(category_overrides or {}).get(
            "category_type", "TRANSIT_PASS"
        ),
        unit_price_cents=unit_price_cents,
        **(media_overrides or {}),
    )
    election = make_election(
        api,
        base["employee"]["id"],
        base["window"]["id"],
        base["category"]["id"],
        base["account"]["id"],
        pretax_amount_cents=pretax_amount_cents,
        transit_media_id=media["id"],
        media_quantity=media_quantity,
    )
    batch = make_open_batch(api, base["window"]["id"], region_code, seal_user_id)
    order = make_media_order(
        api,
        election["id"],
        media["id"],
        batch["id"],
        seal_user_id,
        quantity=media_quantity,
        coverage_start_at=coverage_start_at,
        coverage_end_at=coverage_end_at,
    )
    result = dict(base)
    result.update({"media": media, "election": election, "batch": batch, "order": order})
    if stop_after == "ordered":
        return result

    seal_headers = make_order_desk_headers(seal_user_id)
    result["batch"] = get_success_data(api.seal_order_batch(batch["id"], seal_headers))
    if stop_after == "sealed":
        return result

    result["batch"] = get_success_data(
        api.release_order_batch(batch["id"], make_order_desk_headers(release_user_id))
    )
    result["order"] = get_success_data(api.get_media_order(order["id"], seal_headers))
    if stop_after == "released":
        return result

    result["order"] = get_success_data(
        api.ship_media_order(order["id"], {"tracking_ref": "TRK-FIXTURE-1"}, seal_headers)
    )
    if stop_after == "shipped":
        return result

    result["order"] = get_success_data(
        api.confirm_media_order_delivery(order["id"], seal_headers)
    )
    result["batch"] = get_success_data(api.get_order_batch(batch["id"], seal_headers))
    return result


# =============================================================================
# Tier 4: accumulation and threshold targeting
# =============================================================================
def make_roster(
    api,
    employer_id: str,
    count: int,
    work_region_code: str = REGION_AUS,
    hire_date: str = "2026-01-05T00:00:00Z",
    prefix: str = "ROSTER",
    headers: Optional[Dict] = None,
) -> List[Dict[str, Any]]:
    """``count`` ACTIVE employees, all in one region, for headcount thresholds."""
    headers = headers or PROGRAM_ADMIN
    return [
        make_employee(
            api,
            employer_id,
            headers,
            external_ref=f"{prefix}-{index:02d}",
            work_region_code=work_region_code,
            hire_date=hire_date,
        )
        for index in range(1, count + 1)
    ]


def make_batch_with_n_lines(
    api,
    line_count: int,
    region_code: str = REGION_AUS,
    unit_price_cents: int = 1000,
    seal_user_id: str = "desk-build",
    employer_overrides: Optional[Dict] = None,
    window_overrides: Optional[Dict] = None,
) -> Dict[str, Any]:
    """One OPEN batch carrying ``line_count`` PENDING lines, each from a distinct
    employee so no supersede-cancel can remove a line.

    Returns ``{"employer", "category", "window", "media", "batch", "elections",
    "orders", "employees", "accounts"}``.
    """
    built = make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[{"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000}],
        region_code=region_code,
        **(employer_overrides or {}),
    )
    employer = built["employer"]
    category = built["categories"][0]
    media = make_transit_media(
        api,
        region_code=region_code,
        eligible_category_type="TRANSIT_PASS",
        unit_price_cents=unit_price_cents,
    )
    window = make_open_window(api, employer["id"], PROGRAM_ADMIN, **(window_overrides or {}))
    batch = make_open_batch(api, window["id"], region_code, seal_user_id)

    employees, accounts, elections, orders = [], [], [], []
    for index in range(line_count):
        enrolled = make_enrolled_employee(
            api,
            employer["id"],
            category["id"],
            PROGRAM_ADMIN,
            external_ref=f"LINE-{index + 1:02d}",
            work_region_code=region_code,
        )
        election = make_election(
            api,
            enrolled["employee"]["id"],
            window["id"],
            category["id"],
            enrolled["account"]["id"],
            pretax_amount_cents=unit_price_cents,
            transit_media_id=media["id"],
            media_quantity=1,
        )
        order = make_media_order(
            api, election["id"], media["id"], batch["id"], seal_user_id, quantity=1
        )
        employees.append(enrolled["employee"])
        accounts.append(enrolled["account"])
        elections.append(election)
        orders.append(order)

    return {
        "employer": employer,
        "category": category,
        "window": window,
        "media": media,
        "batch": batch,
        "employees": employees,
        "accounts": accounts,
        "elections": elections,
        "orders": orders,
    }


def make_pending_docs_transaction(
    api,
    amount_cents: int = 3000,
    merchant_category_code: int = 4111,
    opening_rollover_cents: int = 10000,
    pretax_amount_cents: int = 5000,
    region_code: str = "US-IL-CHI",
    transaction_at: str = DEFAULT_CLOCK,
) -> Dict[str, Any]:
    """A swipe above the auto-substantiation ceiling, so it lands in PENDING_DOCS.

    Returns ``{"employer", "category", "employee", "account", "window",
    "election", "transaction"}``.
    """
    base = make_program_with_participant(
        api,
        region_code=region_code,
        account_overrides={"opening_rollover_cents": opening_rollover_cents},
    )
    election = make_election(
        api,
        base["employee"]["id"],
        base["window"]["id"],
        base["category"]["id"],
        base["account"]["id"],
        pretax_amount_cents=pretax_amount_cents,
    )
    transaction = get_success_data(
        api.create_card_transaction(
            f.card_transaction_payload(
                election["id"],
                amount_cents=amount_cents,
                merchant_category_code=merchant_category_code,
                transaction_at=transaction_at,
            ),
            PROGRAM_ADMIN,
        )
    )
    base["election"] = election
    base["transaction"] = transaction
    return base


def make_denied_transaction(
    api,
    deny_user_id: str = "reviewer-deny",
    amount_cents: int = 3000,
    **kwargs,
) -> Dict[str, Any]:
    """A swipe denied by a reviewer, i.e. the receivable cascade has already run."""
    base = make_pending_docs_transaction(api, amount_cents=amount_cents, **kwargs)
    base["transaction"] = get_success_data(
        api.deny_substantiation(
            base["transaction"]["id"],
            {"reason": "no receipt supplied within the audit window"},
            make_compliance_reviewer_headers(deny_user_id),
        )
    )
    return base


def make_submitted_claim(
    api, claimed_amount_cents: Optional[int] = None, doc_type: str = "RECEIPT", **kwargs
) -> Dict[str, Any]:
    """A SUBMITTED substantiation claim over a PENDING_DOCS swipe."""
    base = make_pending_docs_transaction(api, **kwargs)
    amount = (
        claimed_amount_cents
        if claimed_amount_cents is not None
        else base["transaction"]["amount_cents"]
    )
    base["claim"] = get_success_data(
        api.create_substantiation_claim(
            f.substantiation_claim_payload(
                base["transaction"]["id"], amount, doc_type=doc_type
            ),
            PROGRAM_ADMIN,
        )
    )
    return base


# =============================================================================
# Tier 5: finalization and terminal states
# =============================================================================
def make_draft_payroll_file(
    api, employer_id: str, period_month: str = "2026-08", payroll_user_id: str = "pay-1"
) -> Dict[str, Any]:
    return get_success_data(
        api.create_payroll_file(
            f.payroll_file_payload(employer_id, period_month),
            make_payroll_processor_headers(payroll_user_id),
        )
    )


def make_generated_payroll_file(
    api, employer_id: str, period_month: str = "2026-08", payroll_user_id: str = "pay-1"
) -> Dict[str, Any]:
    headers = make_payroll_processor_headers(payroll_user_id)
    payroll_file = make_draft_payroll_file(api, employer_id, period_month, payroll_user_id)
    return get_success_data(api.generate_payroll_file(payroll_file["id"], headers))


def make_transmitted_payroll_file(
    api, employer_id: str, period_month: str = "2026-08", payroll_user_id: str = "pay-1"
) -> Dict[str, Any]:
    headers = make_payroll_processor_headers(payroll_user_id)
    payroll_file = make_generated_payroll_file(
        api, employer_id, period_month, payroll_user_id
    )
    return get_success_data(api.transmit_payroll_file(payroll_file["id"], headers))


def make_retired_category(api, employer_id: str, **overrides) -> Dict[str, Any]:
    category = get_success_data(
        api.create_benefit_category(
            f.benefit_category_payload(employer_id, **overrides), PROGRAM_ADMIN
        )
    )
    return get_success_data(api.retire_benefit_category(category["id"], PROGRAM_ADMIN))


def terminate(
    api, employee_id: str, termination_date: str = "2026-08-05T00:00:00Z"
) -> Dict[str, Any]:
    return get_success_data(
        api.terminate_employee(
            employee_id, {"termination_date": termination_date}, PROGRAM_ADMIN
        )
    )


def month_close(api, employer_id: str, benefit_month: str = "2026-08") -> Dict[str, Any]:
    return get_success_data(
        api.month_close_employer(
            employer_id, {"benefit_month": benefit_month}, PROGRAM_ADMIN
        )
    )


# =============================================================================
# Read-through convenience helpers
# =============================================================================
def read_employer(api, employer_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_employer(employer_id, headers or PROGRAM_ADMIN))


def read_employee(api, employee_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_employee(employee_id, headers or PROGRAM_ADMIN))


def read_account(api, account_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_benefit_account(account_id, headers or PROGRAM_ADMIN))


def read_election(api, election_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_election(election_id, headers or PROGRAM_ADMIN))


def read_window(api, window_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_election_window(window_id, headers or PROGRAM_ADMIN))


def read_batch(api, batch_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_order_batch(batch_id, headers or make_order_desk_headers("desk-reader"))
    )


def read_media_order(api, order_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_media_order(order_id, headers or make_order_desk_headers("desk-reader"))
    )


def read_transaction(api, transaction_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_card_transaction(transaction_id, headers or PROGRAM_ADMIN)
    )


def read_claim(api, claim_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_substantiation_claim(claim_id, headers or PROGRAM_ADMIN)
    )


def read_payroll_file(api, file_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_payroll_file(file_id, headers or make_payroll_processor_headers())
    )


def read_ledger(api, account_id: str, headers: Optional[Dict] = None, **params) -> List[Dict[str, Any]]:
    """The account's ledger rows, oldest first."""
    query = {"limit": 100}
    query.update(params)
    return get_success_data(
        api.list_account_ledger_entries(account_id, headers or PROGRAM_ADMIN, query)
    )
