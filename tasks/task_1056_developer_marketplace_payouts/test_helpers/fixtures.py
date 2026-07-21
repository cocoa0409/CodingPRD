"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
the lenient validator so a broken precondition surfaces as a setup failure
rather than a confusing assertion inside the test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_app_payload,
    create_chargeback_payload,
    create_developer_payload,
    create_payout_batch_payload,
    create_policy_case_payload,
    create_pricing_plan_payload,
    create_purchase_payload,
    create_refund_payload,
    create_revenue_share_tier_payload,
    create_tax_jurisdiction_payload,
    next_ref,
)
from .test_users import (
    TEST_USERS,
    make_developer_headers,
    make_policy_officer_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["review_agent_headers"]
OFFICER = TEST_USERS["policy_officer_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]
STORE = TEST_USERS["storefront_headers"]

T0 = "2026-07-01T00:00:00Z"


# ---------------------------------------------------------------- clock ----
def set_clock(api, to_iso8601: str):
    """Move the server's logical clock."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# -------------------------------------------------------- configuration ----
def configure_jurisdiction(api, country_code="US", vat_rate_bps=0,
                           marketplace_facilitator=True):
    payload = create_tax_jurisdiction_payload(
        country_code=country_code,
        vat_rate_bps=vat_rate_bps,
        marketplace_facilitator=marketplace_facilitator,
    )
    return get_success_data(api.create_tax_jurisdiction(payload, ADMIN))


def configure_tier(api, label="BASE", min_cumulative_base_cents=0,
                   developer_share_bps=7000):
    payload = create_revenue_share_tier_payload(
        label=label,
        min_cumulative_base_cents=min_cumulative_base_cents,
        developer_share_bps=developer_share_bps,
    )
    return get_success_data(api.create_revenue_share_tier(payload, ADMIN))


def configure_marketplace(api, clock=T0, jurisdictions=None, tiers=None):
    """Clock + jurisdictions + revenue-share ladder in one call.

    `jurisdictions` is a list of (country_code, vat_rate_bps, facilitator);
    `tiers` is a list of (label, min_cumulative_base_cents, developer_share_bps).
    """
    if clock is not None:
        set_clock(api, clock)
    made_j = []
    for country, bps, facilitator in (jurisdictions or [("US", 0, True)]):
        made_j.append(configure_jurisdiction(api, country, bps, facilitator))
    made_t = []
    for label, min_base, bps in (tiers if tiers is not None else [("BASE", 0, 7000)]):
        made_t.append(configure_tier(api, label, min_base, bps))
    return {"jurisdictions": made_j, "tiers": made_t}


# ----------------------------------------------------------- developers ----
def create_developer(api, **overrides):
    return get_success_data(api.create_developer(create_developer_payload(**overrides), ADMIN))


def create_verified_developer(api, **overrides):
    """Open an account and move it PENDING_VERIFICATION -> ACTIVE."""
    developer = create_developer(api, **overrides)
    return get_success_data(api.verify_developer(developer["id"], ADMIN))


def read_developer(api, developer_id, headers=None):
    return get_success_data(api.get_developer(developer_id, headers or ADMIN))


def developer_version(api, developer_id) -> int:
    return read_developer(api, developer_id)["version"]


def set_payout_hold(api, developer_id, hold: bool, reason="risk review"):
    """Set or clear the hold, always carrying the current observed version."""
    payload = {
        "hold": hold,
        "expected_developer_version": developer_version(api, developer_id),
        "reason": reason,
    }
    return get_success_data(api.set_payout_hold(developer_id, payload, FINANCE))


def set_tax_profile(api, developer_id, tax_id_provided: bool, reason=None):
    payload = {"tax_id_provided": tax_id_provided}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api.set_tax_profile(developer_id, payload, ADMIN))


# ----------------------------------------------------------------- apps ----
def create_draft_app(api, developer_id, **overrides):
    payload = create_app_payload(developer_id, **overrides)
    return get_success_data(api.create_app(payload, make_developer_headers(developer_id)))


def app_version(api, app_id, developer_id) -> int:
    data = get_success_data(api.get_app(app_id, make_developer_headers(developer_id)))
    return data["version"]


def add_pricing_plan(api, app_id, developer_id, expected_app_version=None, **overrides):
    """Attach a plan, reading the app's current version unless one is pinned."""
    if expected_app_version is None:
        expected_app_version = app_version(api, app_id, developer_id)
    payload = create_pricing_plan_payload(expected_app_version, **overrides)
    return get_success_data(
        api.create_pricing_plan(app_id, payload, make_developer_headers(developer_id))
    )


def submit_for_review(api, app_id, developer_id, submitted_notes="v1"):
    return get_success_data(
        api.submit_app_for_review(
            app_id, {"submitted_notes": submitted_notes}, make_developer_headers(developer_id)
        )
    )


def decide_review(api, submission_id, outcome="PASSED", decision_reason="ok"):
    """Claim the round for triage and record its outcome."""
    get_success_data(api.triage_review_submission(submission_id, AGENT))
    return get_success_data(
        api.decide_review_submission(
            submission_id, {"outcome": outcome, "decision_reason": decision_reason}, AGENT
        )
    )


def take_app_through_review(api, app_id, developer_id, outcome="PASSED",
                            submitted_notes="v1", decision_reason="ok"):
    """Submit -> triage -> decide. Returns the ReviewSubmission."""
    submission = submit_for_review(api, app_id, developer_id, submitted_notes)
    return decide_review(api, submission["id"], outcome, decision_reason)


def publish_app(api, app_id, developer_id):
    return get_success_data(api.publish_app(app_id, make_developer_headers(developer_id)))


def setup_approved_app(api, developer_id=None, plan_overrides=None, app_overrides=None,
                       developer_overrides=None, verify=True):
    """Verified developer + app + ACTIVE plan + passed review. App is APPROVED."""
    if developer_id is None:
        maker = create_verified_developer if verify else create_developer
        developer = maker(api, **(developer_overrides or {}))
        developer_id = developer["id"]
    else:
        developer = read_developer(api, developer_id)
    app = create_draft_app(api, developer_id, **(app_overrides or {}))
    plan = add_pricing_plan(api, app["id"], developer_id, **(plan_overrides or {}))
    take_app_through_review(api, app["id"], developer_id)
    return {"developer": developer, "developer_id": developer_id, "app": app,
            "app_id": app["id"], "plan": plan, "plan_id": plan["id"]}


def setup_live_app(api, developer_id=None, plan_overrides=None, app_overrides=None,
                   developer_overrides=None):
    """The standard preamble: verified ACTIVE developer owning a LIVE listing
    with one ACTIVE pricing plan. Returns developer / app / plan and their ids."""
    ctx = setup_approved_app(
        api,
        developer_id=developer_id,
        plan_overrides=plan_overrides,
        app_overrides=app_overrides,
        developer_overrides=developer_overrides,
    )
    ctx["app"] = publish_app(api, ctx["app_id"], ctx["developer_id"])
    return ctx


def setup_marketplace_with_live_app(api, clock=T0, jurisdictions=None, tiers=None,
                                    plan_overrides=None, app_overrides=None,
                                    developer_overrides=None):
    """configure_marketplace + setup_live_app - the most common starting point."""
    config = configure_marketplace(api, clock=clock, jurisdictions=jurisdictions, tiers=tiers)
    ctx = setup_live_app(
        api,
        plan_overrides=plan_overrides,
        app_overrides=app_overrides,
        developer_overrides=developer_overrides,
    )
    ctx["config"] = config
    return ctx


# ------------------------------------------------------------ purchases ----
def record_purchase(api, app_id, plan_id, **overrides):
    payload = create_purchase_payload(app_id, plan_id, **overrides)
    return get_success_data(api.create_purchase(payload, STORE))


def capture_purchase(api, purchase_id):
    return get_success_data(api.capture_purchase(purchase_id, STORE))


def record_and_capture(api, app_id, plan_id, **overrides):
    """Record a purchase and capture it, returning the captured Purchase."""
    purchase = record_purchase(api, app_id, plan_id, **overrides)
    return capture_purchase(api, purchase["id"])


def single_line_purchase(unit_price_cents, quantity=1, sku="base"):
    return [{"sku": sku, "unit_price_cents": unit_price_cents, "quantity": quantity}]


# -------------------------------------------------------------- refunds ----
def request_refund(api, purchase_id, amount_cents, reason="BUYER_REQUEST"):
    payload = create_refund_payload(amount_cents=amount_cents, reason=reason)
    return get_success_data(api.request_refund(purchase_id, payload, STORE))


def approve_refund(api, refund_id):
    return get_success_data(api.decide_refund(refund_id, {"outcome": "APPROVED"}, FINANCE))


def execute_refund_flow(api, purchase_id, amount_cents, reason="BUYER_REQUEST"):
    """Request -> approve -> execute. Returns the EXECUTED Refund."""
    refund = request_refund(api, purchase_id, amount_cents, reason)
    approve_refund(api, refund["id"])
    return get_success_data(api.execute_refund(refund["id"], FINANCE))


# ----------------------------------------------------------- chargebacks ----
def file_chargeback(api, purchase_id, amount_cents, network_case_ref=None):
    payload = create_chargeback_payload(
        amount_cents=amount_cents,
        network_case_ref=network_case_ref or next_ref("CB"),
    )
    return get_success_data(api.create_chargeback(purchase_id, payload, STORE))


def resolve_chargeback(api, chargeback_id, outcome):
    return get_success_data(
        api.resolve_chargeback(chargeback_id, {"outcome": outcome}, FINANCE)
    )


def lose_chargeback(api, purchase_id, amount_cents, network_case_ref=None):
    """File a dispute and resolve it LOST. Returns the LOST Chargeback."""
    chargeback = file_chargeback(api, purchase_id, amount_cents, network_case_ref)
    return resolve_chargeback(api, chargeback["id"], "LOST")


# ------------------------------------------------------------ payouts -----
def open_batch(api, payout_currency="USD", period_start="2026-07-01T00:00:00Z",
               period_end="2026-08-01T00:00:00Z"):
    payload = create_payout_batch_payload(
        payout_currency=payout_currency,
        period_start=period_start,
        period_end=period_end,
    )
    return get_success_data(api.create_payout_batch(payload, FINANCE))


def calculate_batch(api, batch_id):
    return get_success_data(api.calculate_payout_batch(batch_id, FINANCE))


def submit_batch(api, batch_id):
    return get_success_data(api.submit_payout_batch(batch_id, FINANCE))


def approve_batch(api, batch_id):
    return get_success_data(api.approve_payout_batch(batch_id, ADMIN))


def pay_batch(api, batch_id, outcome="SUCCEEDED", failure_reason=None):
    payload = {"outcome": outcome}
    if failure_reason is not None:
        payload["failure_reason"] = failure_reason
    return get_success_data(api.pay_payout_batch(batch_id, payload, FINANCE))


def run_batch_to_paid(api, batch_id):
    """calculate -> submit -> approve -> pay SUCCEEDED."""
    calculate_batch(api, batch_id)
    submit_batch(api, batch_id)
    approve_batch(api, batch_id)
    return pay_batch(api, batch_id, "SUCCEEDED")


def batch_lines(api, batch_id, params=None):
    data, _meta = _paginated(api.list_payout_batch_lines(batch_id, FINANCE, params))
    return data


def only_line(api, batch_id):
    """The single PayoutLine materialised for a batch."""
    lines = batch_lines(api, batch_id)
    assert len(lines) == 1, f"expected exactly 1 payout line, got {len(lines)}"
    return lines[0]


def open_and_calculate_batch(api, payout_currency="USD",
                             period_start="2026-07-01T00:00:00Z",
                             period_end="2026-08-01T00:00:00Z"):
    batch = open_batch(api, payout_currency, period_start, period_end)
    return calculate_batch(api, batch["id"])


def setup_paid_batch_for_purchase(api, app_id, plan_id, unit_price_cents,
                                  period_start="2026-07-01T00:00:00Z",
                                  period_end="2026-08-01T00:00:00Z", **purchase_overrides):
    """Capture one purchase and run a batch all the way to PAID.

    Returns the captured purchase, the PAID batch and its single line.
    """
    purchase = record_and_capture(
        api, app_id, plan_id,
        line_items=single_line_purchase(unit_price_cents),
        **purchase_overrides,
    )
    batch = open_batch(api, "USD", period_start, period_end)
    line_before = None
    calculate_batch(api, batch["id"])
    lines = batch_lines(api, batch["id"])
    if lines:
        line_before = lines[0]
    submit_batch(api, batch["id"])
    approve_batch(api, batch["id"])
    paid = pay_batch(api, batch["id"], "SUCCEEDED")
    return {"purchase": purchase, "batch": paid, "batch_id": batch["id"],
            "line": line_before}


# --------------------------------------------------------- policy cases ----
def open_policy_case(api, app_id, opened_by="officer-open", **overrides):
    payload = create_policy_case_payload(app_id, **overrides)
    return get_success_data(
        api.create_policy_case(payload, make_policy_officer_headers(opened_by))
    )


def investigate_case(api, case_id, officer="officer-open"):
    return get_success_data(
        api.investigate_policy_case(case_id, make_policy_officer_headers(officer))
    )


def decide_case(api, case_id, outcome, rationale="decided", officer="officer-decide"):
    return get_success_data(
        api.decide_policy_case(
            case_id, {"outcome": outcome, "rationale": rationale},
            make_policy_officer_headers(officer),
        )
    )


def uphold_case_on_app(api, app_id, opened_by="officer-open", decided_by="officer-decide",
                       **overrides):
    """Open -> investigate -> decide UPHELD. Fires the full takedown cascade."""
    case = open_policy_case(api, app_id, opened_by=opened_by, **overrides)
    investigate_case(api, case["id"], opened_by)
    return decide_case(api, case["id"], "UPHELD", "confirmed", decided_by)


def appeal_case(api, case_id, developer_id, appeal_statement="please reconsider"):
    return get_success_data(
        api.appeal_policy_case(
            case_id, {"appeal_statement": appeal_statement},
            make_developer_headers(developer_id),
        )
    )


def decide_appeal(api, case_id, outcome, rationale="appeal decided",
                  officer="officer-decide"):
    return get_success_data(
        api.decide_policy_case_appeal(
            case_id, {"outcome": outcome, "rationale": rationale},
            make_policy_officer_headers(officer),
        )
    )


def accumulate_policy_strikes(api, developer_id, count, name_prefix="Strike"):
    """Delist `count` throwaway DRAFT listings so the developer carries
    exactly `count` policy strikes without any of them suspending it."""
    delisted = []
    for i in range(count):
        app = create_draft_app(api, developer_id, name=f"{name_prefix} {i + 1}")
        delisted.append(
            get_success_data(
                api.delist_app(app["id"], {"reason": f"prior violation {i + 1}"}, OFFICER)
            )
        )
    return delisted


# --------------------------------------------------------------- ledger ----
def _paginated(response):
    body = response.json()
    assert response.status_code == 200, f"list call failed: {response.status_code} {body}"
    return body["data"], body.get("meta", {})


def ledger_entries(api, **filters):
    data, _meta = _paginated(api.list_ledger_entries(FINANCE, {"limit": 100, **filters}))
    return data


def unsettled_ledger_entries(api, developer_id):
    """A developer's ledger rows whose `settled` flag is false."""
    return [e for e in ledger_entries(api, developer_id=developer_id) if not e["settled"]]


def ledger_sum(api, **filters):
    return sum(e["amount_cents"] for e in ledger_entries(api, **filters))


def developer_summary(api, developer_id, headers=None):
    return get_success_data(api.get_developer_summary(developer_id, headers or FINANCE))
