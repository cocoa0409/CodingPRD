"""Composite setup helpers.

Every test starts against an empty database, so each fixture below builds its
preconditions from scratch using only declared endpoints.  Fixtures are layered:

  Tier 1  regime / party primitives and single state transitions
  Tier 2  entity hierarchy (agreement + attached policies)
  Tier 3  full lifecycle shortcuts (submitted / verified / active notes)
  Tier 4  accumulation and threshold targeting (past-due, late fee, notice)
  Tier 5  finalization and terminal states (cancellation, carrier return)

`get_success_data` is used internally so that a fixture surfaces the body it
built without turning a setup problem into an assertion failure inside the
fixture itself.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .test_users import (
    ANALYST_NOTICE,
    ANALYST_ORIGIN,
    ANALYST_POA,
    COMPLIANCE,
    make_insured_headers,
    make_insurer_headers,
    make_producer_agent_headers,
)

CLOCK_ORIGINATION = "2026-08-15T00:00:00Z"


def _d(response) -> Dict[str, Any]:
    return get_success_data(response)


# ===========================================================================
# Tier 1 — regime, licence and party primitives
# ===========================================================================
def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock forward and return the echoed state."""
    return _d(api.set_clock(to_iso8601, COMPLIANCE))


def create_state_regime(
    api: ApiClient,
    rule_payload: Optional[Dict[str, Any]] = None,
    license_payload: Optional[Dict[str, Any]] = None,
    with_license: bool = True,
) -> Dict[str, Any]:
    """Register one statutory regime, optionally with an effective licence."""
    rule = _d(
        api.create_state_rate_rule(
            rule_payload or factories.tx_state_rate_rule(), COMPLIANCE
        )
    )
    result: Dict[str, Any] = {"rule": rule, "rule_id": rule["id"]}
    if with_license:
        lic = _d(
            api.create_license(
                rule["id"],
                license_payload
                or factories.license_payload(license_number="PFC-TX-001"),
                COMPLIANCE,
            )
        )
        result["license"] = lic
        result["license_id"] = lic["id"]
    return result


def create_tx_regime(api: ApiClient, **rule_overrides: Any) -> Dict[str, Any]:
    """The canonical TX regime plus an effective licence."""
    return create_state_regime(
        api,
        rule_payload=factories.tx_state_rate_rule(**rule_overrides),
        license_payload=factories.license_payload(license_number="PFC-TX-001"),
    )


def create_ca_regime(api: ApiClient, **rule_overrides: Any) -> Dict[str, Any]:
    """The canonical CA regime plus an effective licence."""
    return create_state_regime(
        api,
        rule_payload=factories.ca_state_rate_rule(**rule_overrides),
        license_payload=factories.license_payload(license_number="PFC-CA-001"),
    )


def create_parties(
    api: ApiClient,
    insured_payload: Optional[Dict[str, Any]] = None,
    agent_payload: Optional[Dict[str, Any]] = None,
    insurer_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One borrower, one producing agency and one carrier, with their headers.

    The three entity-backed roles are threaded through per-instance header
    builders keyed on the real row ids, because those roles authenticate as the
    entity itself.
    """
    insured = _d(api.create_insured(insured_payload or factories.insured(), ANALYST_ORIGIN))
    agent = _d(
        api.create_agent(agent_payload or factories.producer_agent(), COMPLIANCE)
    )
    insurer = _d(
        api.create_insurer(insurer_payload or factories.insurer(), COMPLIANCE)
    )
    return {
        "insured": insured,
        "insured_id": insured["id"],
        "insured_headers": make_insured_headers(insured["id"]),
        "agent": agent,
        "agent_id": agent["id"],
        "agent_headers": make_producer_agent_headers(agent["id"]),
        "insurer": insurer,
        "insurer_id": insurer["id"],
        "insurer_headers": make_insurer_headers(insurer["id"]),
    }


def origination_context(
    api: ApiClient,
    clock: str = CLOCK_ORIGINATION,
    regime: str = "TX",
    rule_overrides: Optional[Dict[str, Any]] = None,
    agent_payload: Optional[Dict[str, Any]] = None,
    insured_payload: Optional[Dict[str, Any]] = None,
    insurer_payload: Optional[Dict[str, Any]] = None,
    with_license: bool = True,
) -> Dict[str, Any]:
    """Clock + statutory regime + licence + the three counterparties.

    This is the common prelude of every origination flow.
    """
    set_clock(api, clock)
    rule_overrides = rule_overrides or {}
    if regime == "CA":
        rule_payload = factories.ca_state_rate_rule(**rule_overrides)
        license_number = "PFC-CA-001"
    else:
        rule_payload = factories.tx_state_rate_rule(**rule_overrides)
        license_number = "PFC-TX-001"
    ctx = create_state_regime(
        api,
        rule_payload=rule_payload,
        license_payload=factories.license_payload(license_number=license_number),
        with_license=with_license,
    )
    ctx.update(
        create_parties(
            api,
            insured_payload=insured_payload,
            agent_payload=agent_payload,
            insurer_payload=insurer_payload,
        )
    )
    ctx["clock"] = clock
    return ctx


# ===========================================================================
# Tier 2 — entity hierarchy: an agreement with its attached policies
# ===========================================================================
def draft_agreement(
    api: ApiClient,
    ctx: Dict[str, Any],
    policies: Optional[List[Dict[str, Any]]] = None,
    **agreement_overrides: Any,
) -> Dict[str, Any]:
    """A DRAFT agreement under `ctx`, with zero or more policies attached."""
    payload = factories.agreement(
        ctx["insured_id"],
        ctx["agent_id"],
        ctx["rule_id"],
        **agreement_overrides,
    )
    agreement = _d(api.create_agreement(payload, ANALYST_ORIGIN))
    policy_rows: List[Dict[str, Any]] = []
    if policies is None:
        policies = [factories.financed_policy(ctx["insurer_id"])]
    for policy_payload in policies:
        policy_rows.append(
            _d(api.attach_policy(agreement["id"], policy_payload, ANALYST_ORIGIN))
        )
    bundle = dict(ctx)
    bundle.update(
        {
            "agreement": agreement,
            "agreement_id": agreement["id"],
            "policies": policy_rows,
            "policy_ids": [row["id"] for row in policy_rows],
        }
    )
    if policy_rows:
        bundle["policy_id"] = policy_rows[0]["id"]
    return bundle


# ===========================================================================
# Tier 3 — full lifecycle shortcuts
# ===========================================================================
def submitted_agreement(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    policies: Optional[List[Dict[str, Any]]] = None,
    clock: str = CLOCK_ORIGINATION,
    regime: str = "TX",
    rule_overrides: Optional[Dict[str, Any]] = None,
    agent_payload: Optional[Dict[str, Any]] = None,
    **agreement_overrides: Any,
) -> Dict[str, Any]:
    """An agreement in PENDING_VERIFICATION with its PROVISIONAL quote priced."""
    if ctx is None:
        ctx = origination_context(
            api,
            clock=clock,
            regime=regime,
            rule_overrides=rule_overrides,
            agent_payload=agent_payload,
        )
    bundle = draft_agreement(api, ctx, policies=policies, **agreement_overrides)
    bundle["submitted"] = _d(api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN))
    return bundle


def verify_policy(
    api: ApiClient,
    bundle: Dict[str, Any],
    policy_id: str,
    insurer_payload: Optional[Dict[str, Any]] = None,
    agent_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """File both attestations on one policy and return the two records.

    The carrier files first, then the agency, each authenticating as its own row.
    """
    insurer_record = _d(
        api.create_verification(
            policy_id,
            insurer_payload or factories.confirmed_verification(),
            bundle["insurer_headers"],
        )
    )
    agent_record = _d(
        api.create_verification(
            policy_id,
            agent_payload or factories.confirmed_verification(),
            bundle["agent_headers"],
        )
    )
    return {"insurer_verification": insurer_record, "agent_verification": agent_record}


def verified_agreement(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    policies: Optional[List[Dict[str, Any]]] = None,
    verifications: Optional[List[Dict[str, Any]]] = None,
    clock: str = CLOCK_ORIGINATION,
    regime: str = "TX",
    rule_overrides: Optional[Dict[str, Any]] = None,
    agent_payload: Optional[Dict[str, Any]] = None,
    **agreement_overrides: Any,
) -> Dict[str, Any]:
    """A submitted agreement whose every policy has both attestations filed.

    `verifications` may supply one payload per policy, applied to BOTH parties,
    so a CORRECTED pair can be threaded through without extra plumbing.
    """
    bundle = submitted_agreement(
        api,
        ctx=ctx,
        policies=policies,
        clock=clock,
        regime=regime,
        rule_overrides=rule_overrides,
        agent_payload=agent_payload,
        **agreement_overrides,
    )
    records = []
    for index, policy_id in enumerate(bundle["policy_ids"]):
        payload = None
        if verifications is not None and index < len(verifications):
            payload = verifications[index]
        records.append(
            verify_policy(
                api,
                bundle,
                policy_id,
                insurer_payload=payload,
                agent_payload=payload,
            )
        )
    bundle["verifications"] = records
    return bundle


def active_agreement(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    policies: Optional[List[Dict[str, Any]]] = None,
    verifications: Optional[List[Dict[str, Any]]] = None,
    clock: str = CLOCK_ORIGINATION,
    activate_at: Optional[str] = None,
    regime: str = "TX",
    rule_overrides: Optional[Dict[str, Any]] = None,
    agent_payload: Optional[Dict[str, Any]] = None,
    **agreement_overrides: Any,
) -> Dict[str, Any]:
    """An ACTIVE note with its FINAL quote and its installment schedule cut."""
    bundle = verified_agreement(
        api,
        ctx=ctx,
        policies=policies,
        verifications=verifications,
        clock=clock,
        regime=regime,
        rule_overrides=rule_overrides,
        agent_payload=agent_payload,
        **agreement_overrides,
    )
    if activate_at is not None:
        set_clock(api, activate_at)
        bundle["clock"] = activate_at
    bundle["activated"] = _d(
        api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN)
    )
    return bundle


def canonical_600k_note(
    api: ApiClient,
    policy_number: str = "MC-TX-6001",
    clock: str = CLOCK_ORIGINATION,
    activate_at: Optional[str] = None,
    agent_payload: Optional[Dict[str, Any]] = None,
    **agreement_overrides: Any,
) -> Dict[str, Any]:
    """The 600k note, ACTIVE.

    Single 600000 policy, down payment 100000, service fee 2000, six
    installments, first due 2026-10-01.
    """
    ctx = origination_context(api, clock=clock, agent_payload=agent_payload)
    return active_agreement(
        api,
        ctx=ctx,
        policies=[
            factories.financed_policy(
                ctx["insurer_id"], policy_number=policy_number
            )
        ],
        activate_at=activate_at,
        **agreement_overrides,
    )


def tx9_note(
    api: ApiClient,
    clock: str = CLOCK_ORIGINATION,
    activate_at: str = "2026-09-01T00:00:00Z",
    single_policy: bool = True,
) -> Dict[str, Any]:
    """The TX9 note, ACTIVE: attested premium 1250000 over nine installments.

    With `single_policy` the 1250000 basis arrives as one CONFIRMED 1550000
    policy less nothing; with two policies it arrives as a CORRECTED 1200000
    policy at 1250000 plus a CONFIRMED 300000 policy, which is the shape the
    dual-basis recipes need.
    """
    ctx = origination_context(api, clock=clock)
    if single_policy:
        policies = [
            factories.financed_policy(
                ctx["insurer_id"],
                policy_number="MC-TX-9001",
                gross_premium_cents=1550000,
            )
        ]
        verifications = None
    else:
        policies = [
            factories.financed_policy(
                ctx["insurer_id"],
                policy_number="MC-TX-1001",
                gross_premium_cents=1200000,
                min_earned_days=30,
            ),
            factories.financed_policy(
                ctx["insurer_id"],
                policy_number="MC-TX-1002",
                gross_premium_cents=300000,
            ),
        ]
        verifications = [
            factories.corrected_verification(1250000),
            factories.confirmed_verification(),
        ]
    return active_agreement(
        api,
        ctx=ctx,
        policies=policies,
        verifications=verifications,
        activate_at=activate_at,
        down_payment_cents=300000,
        service_fee_cents=2000,
        installment_count=9,
        first_installment_due_date="2026-10-01",
    )


# ===========================================================================
# Tier 4 — accumulation and threshold targeting
# ===========================================================================
def run_servicing(api: ApiClient) -> Dict[str, Any]:
    """One servicing pass at the current logical clock."""
    return _d(api.run_servicing(COMPLIANCE))


def advance_and_service(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the clock forward, then run the servicing pass."""
    set_clock(api, to_iso8601)
    return run_servicing(api)


def post_payment(
    api: ApiClient,
    agreement_id: str,
    amount_cents: int,
    received_date: str,
    method: str = "ACH",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return _d(
        api.create_payment(
            agreement_id,
            factories.payment(amount_cents, received_date, method=method),
            headers or ANALYST_ORIGIN,
        )
    )


def delinquent_note(
    api: ApiClient,
    bundle: Optional[Dict[str, Any]] = None,
    service_at: str = "2026-10-12T00:00:00Z",
    **note_kwargs: Any,
) -> Dict[str, Any]:
    """An ACTIVE note carried to LATE with one OUTSTANDING late fee.

    The default clock lands strictly after the first due date plus the grace
    period, which is what makes the servicing pass assess a fee rather than only
    marking the installment past due.
    """
    if bundle is None:
        bundle = canonical_600k_note(api, **note_kwargs)
    bundle["servicing_run"] = advance_and_service(api, service_at)
    fees, _ = _paginated(api.list_late_fees(bundle["agreement_id"], ANALYST_ORIGIN))
    bundle["late_fees"] = fees
    if fees:
        bundle["late_fee_id"] = fees[0]["id"]
        bundle["late_fee_amount_cents"] = fees[0]["amount_cents"]
    bundle["clock"] = service_at
    return bundle


def noticed_note(
    api: ApiClient,
    bundle: Optional[Dict[str, Any]] = None,
    notice_at: Optional[str] = None,
    issuer_headers: Optional[Dict[str, str]] = None,
    **delinquent_kwargs: Any,
) -> Dict[str, Any]:
    """A delinquent note carrying one ISSUED notice of intent to cancel.

    The notice is issued under a handle distinct from the one that later
    executes the power of attorney, because the two must differ.
    """
    if bundle is None:
        bundle = delinquent_note(api, **delinquent_kwargs)
    if notice_at is not None:
        set_clock(api, notice_at)
        bundle["clock"] = notice_at
    notice = _d(
        api.issue_cancellation_notice(
            bundle["agreement_id"], issuer_headers or ANALYST_NOTICE
        )
    )
    bundle["notice"] = notice
    bundle["notice_id"] = notice["id"]
    return bundle


def cured_note(
    api: ApiClient,
    bundle: Optional[Dict[str, Any]] = None,
    cure_amount_cents: Optional[int] = None,
    cure_date: Optional[str] = None,
    **noticed_kwargs: Any,
) -> Dict[str, Any]:
    """A noticed note whose arrears have been paid off, curing the notice.

    The cure tender defaults to the notice's own past_due_amount_cents, which is
    exactly the arrears the notice snapshotted.
    """
    if bundle is None:
        bundle = noticed_note(api, **noticed_kwargs)
    amount = (
        cure_amount_cents
        if cure_amount_cents is not None
        else bundle["notice"]["past_due_amount_cents"]
    )
    received = cure_date or bundle["notice"]["issued_date"]
    bundle["cure_payment"] = post_payment(
        api, bundle["agreement_id"], amount, received
    )
    bundle["cure_payment_id"] = bundle["cure_payment"]["id"]
    return bundle


# ===========================================================================
# Tier 5 — finalization and terminal states
# ===========================================================================
def cancelled_note(
    api: ApiClient,
    bundle: Optional[Dict[str, Any]] = None,
    execute_at: Optional[str] = None,
    executor_headers: Optional[Dict[str, str]] = None,
    **noticed_kwargs: Any,
) -> Dict[str, Any]:
    """A noticed note whose power of attorney has been exercised.

    Execution is performed under a handle that differs from the notice issuer.
    """
    if bundle is None:
        bundle = noticed_note(api, **noticed_kwargs)
    if execute_at is not None:
        set_clock(api, execute_at)
        bundle["clock"] = execute_at
    bundle["execution"] = _d(
        api.execute_cancellation(
            bundle["agreement_id"], executor_headers or ANALYST_POA
        )
    )
    requests, _ = _paginated(
        api.list_carrier_cancellation_requests(
            COMPLIANCE, {"agreement_id": bundle["agreement_id"], "limit": 50}
        )
    )
    bundle["cancel_requests"] = requests
    if requests:
        bundle["cancel_request_id"] = requests[0]["id"]
    return bundle


def settled_note(
    api: ApiClient,
    bundle: Optional[Dict[str, Any]] = None,
    carrier_returned_cents: int = 400000,
    posted_date: str = "2026-10-22",
    **cancelled_kwargs: Any,
) -> Dict[str, Any]:
    """A cancelled note whose only carrier return has been posted.

    Posting the last outstanding return drives the note into its terminal
    settlement state and, when a deficiency remains, mints the agency chargeback.
    """
    if bundle is None:
        bundle = cancelled_note(api, **cancelled_kwargs)
    bundle["return_posting"] = _d(
        api.post_carrier_return(
            bundle["cancel_request_id"],
            factories.return_posting(carrier_returned_cents, posted_date),
            bundle["insurer_headers"],
        )
    )
    chargebacks, _ = _paginated(
        api.list_agent_chargebacks(
            COMPLIANCE, {"agreement_id": bundle["agreement_id"], "limit": 50}
        )
    )
    bundle["chargebacks"] = chargebacks
    if chargebacks:
        bundle["chargeback_id"] = chargebacks[0]["id"]
    return bundle


# ===========================================================================
# Read helpers
# ===========================================================================
def _paginated(response):
    data = get_success_data(response)
    if isinstance(data, list):
        return data, {}
    body = response.json()
    return body.get("data", []), body.get("meta", {})


def read_agreement(
    api: ApiClient, agreement_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return _d(api.get_agreement(agreement_id, headers or ANALYST_ORIGIN))


def read_policy(
    api: ApiClient, policy_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return _d(api.get_policy(policy_id, headers or ANALYST_ORIGIN))


def read_installments(
    api: ApiClient, agreement_id: str, headers: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    rows, _ = _paginated(
        api.list_installments(agreement_id, headers or ANALYST_ORIGIN, {"limit": 100})
    )
    return rows


def read_late_fees(
    api: ApiClient, agreement_id: str, headers: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    rows, _ = _paginated(
        api.list_late_fees(agreement_id, headers or ANALYST_ORIGIN, {"limit": 100})
    )
    return rows


def read_notices(
    api: ApiClient, agreement_id: str, headers: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    rows, _ = _paginated(
        api.list_cancellation_notices(
            agreement_id, headers or ANALYST_ORIGIN, {"limit": 100}
        )
    )
    return rows


def read_verifications(
    api: ApiClient, policy_id: str, headers: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    rows, _ = _paginated(
        api.list_verifications(policy_id, headers or ANALYST_ORIGIN, {"limit": 100})
    )
    return rows


def read_endorsements(
    api: ApiClient, policy_id: str, headers: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    rows, _ = _paginated(
        api.list_endorsements(policy_id, headers or ANALYST_ORIGIN, {"limit": 100})
    )
    return rows


def agreement_version(api: ApiClient, agreement_id: str) -> int:
    return read_agreement(api, agreement_id)["version"]
