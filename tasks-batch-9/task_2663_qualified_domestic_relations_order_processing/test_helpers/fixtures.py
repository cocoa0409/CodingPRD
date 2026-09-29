"""Precondition builders.

The harness restarts the API against an empty database before every test, so
each test builds every row it needs from scratch through the declared endpoints.
These helpers do exactly that and nothing more: they never assert a business
outcome, they only insist the setup call succeeded. Ownership-gated calls are
threaded with the identity of the row that was actually created — a participant
acts as its own `Participant.id`, a payee as its `AlternatePayeeAccount.id`, an
attorney as its `AttorneyAuthorization.id`.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    make_alternate_payee_headers,
    make_attorney_headers,
    make_participant_headers,
)
from .types import (
    APPROACH_SEPARATE_INTEREST,
    HOLD_HELD,
    PROCEDURES_PUBLISHED,
    SOURCE_AFTER_TAX,
    SOURCE_EMPLOYER_MATCH,
    SOURCE_LOAN_RECEIVABLE,
    SOURCE_PRE_TAX_DEFERRAL,
)


# ─── The logical clock ────────────────────────────────────────────────────


def set_clock(client, current_utc):
    """Move the logical clock; this mutates no entity."""
    return get_success_data(
        client.set_current_utc(factories.clock_payload(current_utc), ADMIN_HEADERS)
    )


def run_sweep(client, headers=None):
    return get_success_data(
        client.run_segregation_sweep(headers or ADMIN_HEADERS)
    )


# ─── Plans ────────────────────────────────────────────────────────────────


def create_plan(client, **overrides):
    return get_success_data(
        client.create_plan(factories.plan_payload(**overrides), ADMIN_HEADERS), 201
    )


def set_procedures(client, plan_id, to_status):
    return get_success_data(
        client.set_procedure_status(
            plan_id, factories.procedure_status_payload(to_status), ADMIN_HEADERS
        )
    )


def create_published_plan(client, **overrides):
    """Register a plan and publish its procedures, the state qualification needs."""
    plan = create_plan(client, **overrides)
    set_procedures(client, plan["id"], PROCEDURES_PUBLISHED)
    return get_success_data(client.get_plan(plan["id"], ADMIN_HEADERS))


# ─── Participants, accounts, sources and valuations ───────────────────────


def enroll_participant(client, plan_id, **overrides):
    return get_success_data(
        client.create_participant(
            factories.participant_payload(plan_id, **overrides), ADMIN_HEADERS
        ),
        201,
    )


def open_plan_account(client, participant_id, **overrides):
    return get_success_data(
        client.open_plan_account(
            participant_id, factories.plan_account_payload(**overrides), ADMIN_HEADERS
        ),
        201,
    )


def add_money_source(client, plan_account_id, source_code, balance_cents, **overrides):
    return get_success_data(
        client.create_money_source(
            plan_account_id,
            factories.money_source_payload(source_code, balance_cents, **overrides),
            ADMIN_HEADERS,
        ),
        201,
    )


def add_snapshot(client, plan_account_id, as_of_date, balance_cents, **overrides):
    return get_success_data(
        client.create_valuation_snapshot(
            plan_account_id,
            factories.valuation_snapshot_payload(
                as_of_date, balance_cents, **overrides
            ),
            ADMIN_HEADERS,
        ),
        201,
    )


def read_plan_account(client, plan_account_id):
    return get_success_data(client.get_plan_account(plan_account_id, ADMIN_HEADERS))


def read_money_sources(client, plan_account_id):
    return get_success_data(client.list_money_sources(plan_account_id, ADMIN_HEADERS))


def money_source_balances(client, plan_account_id):
    """Map `source_code` to `balance_cents` for compact balance assertions."""
    return {
        row["source_code"]: row["balance_cents"]
        for row in read_money_sources(client, plan_account_id)
    }


# ─── Cases, counsel and correspondence ────────────────────────────────────


def open_case(client, participant_id, headers=None, **overrides):
    return get_success_data(
        client.create_qdro_case(
            factories.qdro_case_payload(participant_id, **overrides),
            headers or ADMIN_HEADERS,
        ),
        201,
    )


def read_case(client, case_id, headers=None):
    return get_success_data(client.get_qdro_case(case_id, headers or ADMIN_HEADERS))


def authorize_attorney(client, case_id, **overrides):
    """Record counsel; the returned `id` is the acting attorney's `X-User-ID`."""
    return get_success_data(
        client.create_attorney_authorization(
            case_id, factories.attorney_authorization_payload(**overrides), ADMIN_HEADERS
        ),
        201,
    )


def revoke_authorization(client, authorization_id):
    return get_success_data(
        client.revoke_attorney_authorization(authorization_id, ADMIN_HEADERS)
    )


def read_authorizations(client, case_id, **params):
    return get_success_data(
        client.list_attorney_authorizations(case_id, ADMIN_HEADERS, params or None)
    )


def send_manual_communication(client, case_id, **overrides):
    """Manual correspondence is the analyst's exclusive act."""
    return get_success_data(
        client.create_communication(
            case_id, factories.communication_payload(**overrides), ANALYST_HEADERS
        ),
        201,
    )


def read_communications(client, case_id, **params):
    return get_success_data(
        client.list_communications(case_id, ADMIN_HEADERS, params or None)
    )


# ─── Receipt, holds and the revision cycle ────────────────────────────────


def receive_draft(client, case_id, expected_case_version=1, headers=None, **overrides):
    return get_success_data(
        client.create_draft_order(
            factories.draft_order_payload(case_id, expected_case_version, **overrides),
            headers or ADMIN_HEADERS,
        ),
        201,
    )


def read_draft(client, draft_order_id, headers=None):
    return get_success_data(
        client.get_draft_order(draft_order_id, headers or ADMIN_HEADERS)
    )


def read_holds(client, **params):
    return get_success_data(
        client.list_segregation_holds(ADMIN_HEADERS, params or None)
    )


def hold_for_case(client, case_id):
    """Holds are created by cascade, so the list endpoint is the only channel."""
    holds = read_holds(client, qdro_case_id=case_id)
    assert holds, f"expected a segregation hold on case {case_id}"
    return holds[0]


def held_hold_for_case(client, case_id):
    hold = hold_for_case(client, case_id)
    assert hold["status"] == HOLD_HELD, f"expected a HELD hold, got {hold['status']}"
    return hold


def read_hold(client, hold_id):
    return get_success_data(client.get_segregation_hold(hold_id, ADMIN_HEADERS))


def issue_notice(client, draft_order_id, headers=None, **overrides):
    return get_success_data(
        client.create_deficiency_notice(
            draft_order_id,
            factories.deficiency_notice_payload(**overrides),
            headers or ANALYST_HEADERS,
        ),
        201,
    )


def read_notices(client, draft_order_id, **params):
    return get_success_data(
        client.list_deficiency_notices(draft_order_id, ADMIN_HEADERS, params or None)
    )


def resubmit(client, draft_order_id, headers=None, **overrides):
    return get_success_data(
        client.resubmit_draft_order(
            draft_order_id,
            factories.resubmission_payload(**overrides),
            headers or ADMIN_HEADERS,
        )
    )


def qualify(client, draft_order_id, headers=None):
    return get_success_data(
        client.qualify_draft_order(draft_order_id, headers or ADMIN_HEADERS)
    )


def deny(client, draft_order_id, denial_reason, headers=None):
    return get_success_data(
        client.deny_draft_order(
            draft_order_id,
            factories.denial_payload(denial_reason),
            headers or ADMIN_HEADERS,
        )
    )


def release_hold(client, hold_id, headers=None):
    return get_success_data(
        client.release_segregation_hold(hold_id, headers or ADMIN_HEADERS)
    )


# ─── Payee accounts, distributions and reporting ──────────────────────────


def read_ap_accounts(client, case_id, headers=None):
    """A payee account is established by cascade; the case list finds it."""
    return get_success_data(
        client.list_alternate_payee_accounts(case_id, headers or ADMIN_HEADERS)
    )


def ap_account_for_case(client, case_id):
    accounts = read_ap_accounts(client, case_id)
    assert accounts, f"expected an alternate payee account on case {case_id}"
    return accounts[0]


def read_ap_account(client, ap_account_id, headers=None):
    return get_success_data(
        client.get_alternate_payee_account(ap_account_id, headers or ADMIN_HEADERS)
    )


def issue_distribution(
    client, ap_account_id, expected_ap_account_version, gross_amount_cents,
    headers=None, **overrides
):
    return get_success_data(
        client.create_distribution(
            ap_account_id,
            factories.distribution_payload(
                expected_ap_account_version, gross_amount_cents, **overrides
            ),
            headers or ADMIN_HEADERS,
        ),
        201,
    )


def read_distributions(client, ap_account_id, **params):
    return get_success_data(
        client.list_distributions(ap_account_id, ADMIN_HEADERS, params or None)
    )


def void_distribution(client, distribution_id, headers=None):
    return get_success_data(
        client.void_distribution(distribution_id, headers or ADMIN_HEADERS)
    )


def read_tax_reports(client, **params):
    """Corrective lines are appended by cascade; the ledger list finds them."""
    return get_success_data(client.list_tax_reports(ADMIN_HEADERS, params or None))


# ─── Identity threading ───────────────────────────────────────────────────


def participant_headers(participant):
    return make_participant_headers(participant["id"])


def payee_headers(ap_account):
    return make_alternate_payee_headers(ap_account["id"])


def attorney_headers(authorization):
    return make_attorney_headers(authorization["id"])


# ─── Composite scenarios ──────────────────────────────────────────────────

SINGLE_SOURCE = [(SOURCE_PRE_TAX_DEFERRAL, 1000000, {"basis_cents": 0})]

FOUR_SOURCE_MIX = [
    (SOURCE_AFTER_TAX, 100000, {"basis_cents": 60000}),
    (SOURCE_EMPLOYER_MATCH, 1490125, {}),
    (SOURCE_PRE_TAX_DEFERRAL, 2409875, {}),
    (SOURCE_LOAN_RECEIVABLE, 300000, {"is_assignable": False}),
]


def setup_plan_account(
    client,
    plan_name,
    sources=None,
    snapshots=(),
    plan_overrides=None,
    participant_overrides=None,
    account_overrides=None,
):
    """Published plan, one enrolled participant, one funded account."""
    plan = create_published_plan(
        client, plan_name=plan_name, **(plan_overrides or {})
    )
    participant = enroll_participant(
        client, plan["id"], **(participant_overrides or {})
    )
    account = open_plan_account(
        client, participant["id"], **(account_overrides or {})
    )
    created_sources = {}
    for source_code, balance_cents, extra in sources if sources is not None else []:
        created_sources[source_code] = add_money_source(
            client, account["id"], source_code, balance_cents, **extra
        )
    for as_of_date, balance_cents in snapshots:
        add_snapshot(client, account["id"], as_of_date, balance_cents)
    return {
        "plan": plan,
        "participant": participant,
        "account": read_plan_account(client, account["id"]),
        "sources": created_sources,
    }


def setup_case_with_held_hold(
    client,
    plan_name,
    sources=None,
    snapshots=(("2026-06-30", 1000000),),
    clock="2026-09-01T00:00:00Z",
    plan_overrides=None,
    participant_overrides=None,
    account_overrides=None,
    case_overrides=None,
    draft_overrides=None,
):
    """Receipt has happened: the case is under review and the funds are held."""
    setup = setup_plan_account(
        client,
        plan_name,
        sources if sources is not None else SINGLE_SOURCE,
        snapshots,
        plan_overrides,
        participant_overrides,
        account_overrides,
    )
    if clock is not None:
        set_clock(client, clock)
    case = open_case(client, setup["participant"]["id"], **(case_overrides or {}))
    draft = receive_draft(client, case["id"], case["version"], **(draft_overrides or {}))
    setup.update(
        {
            "case": read_case(client, case["id"]),
            "draft": draft,
            "hold": hold_for_case(client, case["id"]),
            "account": read_plan_account(client, setup["account"]["id"]),
        }
    )
    return setup


def setup_qualified_separate_interest(
    client,
    plan_name,
    qualify_clock="2026-09-15T00:00:00Z",
    **kwargs,
):
    """Carry the setup through to a signed determination and a funded payee."""
    setup = setup_case_with_held_hold(client, plan_name, **kwargs)
    assert setup["draft"]["deficiency_codes"] == [], (
        "this scenario expects a faultless draft, got "
        f"{setup['draft']['deficiency_codes']}"
    )
    if qualify_clock is not None:
        set_clock(client, qualify_clock)
    setup["draft"] = qualify(client, setup["draft"]["id"])
    setup["case"] = read_case(client, setup["case"]["id"])
    setup["hold"] = hold_for_case(client, setup["case"]["id"])
    setup["ap_account"] = ap_account_for_case(client, setup["case"]["id"])
    setup["account"] = read_plan_account(client, setup["account"]["id"])
    assert setup["case"]["approach"] == APPROACH_SEPARATE_INTEREST, (
        "this scenario prices the separate-interest shape"
    )
    return setup
