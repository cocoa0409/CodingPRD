"""State builders that reach interesting states through published endpoints only.

Every builder uses the lenient success reader, so a setup step that answers any
2xx status is accepted; the tests themselves make the strict assertions.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_client import api_client
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.factories import (
    claim_line,
    clock_payload,
    conduct_visit_payload,
    create_agreement_payload,
    create_assignment_payload,
    create_claim_payload,
    create_contract_payload,
    create_enrollment_payload,
    create_food_claim_payload,
    create_license_verification_payload,
    create_order_payload,
    create_provider_payload,
    create_remittance_payload,
    create_review_payload,
    create_substitute_payload,
    create_visit_payload,
)
from test_helpers.test_users import (
    COACH_A_HEADERS,
    COACH_B_HEADERS,
    FISCAL_OFFICER_HEADERS,
    NETWORK_ADMIN_HEADERS,
    NO_AUTH_HEADERS,
    make_provider_headers,
    make_substitute_headers,
)

# ------------------------------------------------------------------- clock


def set_clock(instant, client=api_client, headers=NETWORK_ADMIN_HEADERS):
    """Move the logical clock to ``instant``."""
    return get_success_data(client.set_clock(clock_payload(instant), headers))


# ---------------------------------------------------------------- provider


def apply_provider(client=api_client, **overrides):
    """File a provider application and return the created row."""
    return get_success_data(
        client.apply_provider(create_provider_payload(**overrides), NO_AUTH_HEADERS)
    )


def verify_license(provider_id, client=api_client, headers=NETWORK_ADMIN_HEADERS, **overrides):
    """Record the licensing verification result for ``provider_id``."""
    return get_success_data(
        client.verify_license(
            provider_id, create_license_verification_payload(**overrides), headers
        )
    )


def issue_agreement(
    provider_id, expected_provider_version, client=api_client,
    headers=NETWORK_ADMIN_HEADERS, **overrides
):
    """Issue a membership agreement to ``provider_id``."""
    return get_success_data(
        client.create_agreement(
            create_agreement_payload(provider_id, expected_provider_version, **overrides), headers
        )
    )


def execute_agreement(agreement_id, provider_id, client=api_client):
    """The provider signs the agreement, activating membership."""
    return get_success_data(
        client.execute_agreement(agreement_id, None, make_provider_headers(provider_id))
    )


def active_provider(
    client=api_client,
    apply_overrides=None,
    verification_overrides=None,
    agreement_overrides=None,
):
    """Walk a home from application all the way to ACTIVE membership.

    Returns a context dict with the provider id, the provider's own request
    headers, the executed agreement, and the provider row as last read.
    """
    apply_overrides = dict(apply_overrides or {})
    provider = apply_provider(client, **apply_overrides)
    provider_id = provider["id"]

    verification = {
        key: apply_overrides[key]
        for key in ("license_number", "license_expires_on", "capacity_slots")
        if key in apply_overrides
    }
    verification.update(verification_overrides or {})
    verified = verify_license(provider_id, client, **verification)

    agreement = issue_agreement(
        provider_id, verified["version"], client, **(agreement_overrides or {})
    )
    executed = execute_agreement(agreement["id"], provider_id, client)
    provider_row = get_success_data(client.get_provider(provider_id, NETWORK_ADMIN_HEADERS))

    return {
        "provider_id": provider_id,
        "headers": make_provider_headers(provider_id),
        "agreement_id": agreement["id"],
        "agreement": executed,
        "provider": provider_row,
        "applied": provider,
        "verified": verified,
    }


def reinstate_provider(provider_id, client=api_client, headers=NETWORK_ADMIN_HEADERS):
    """Lift probation from a provider."""
    return get_success_data(client.reinstate_provider(provider_id, None, headers))


def exit_network(provider_id, exit_reason="RETIREMENT", client=api_client,
                 headers=NETWORK_ADMIN_HEADERS):
    """Begin an orderly network exit."""
    return get_success_data(
        client.exit_network(provider_id, {"exit_reason": exit_reason}, headers)
    )


def complete_exit(provider_id, client=api_client, headers=NETWORK_ADMIN_HEADERS):
    """Finalize an exit."""
    return get_success_data(client.complete_exit(provider_id, None, headers))


def revenue_model(provider_id, client=api_client, headers=NETWORK_ADMIN_HEADERS):
    """Read the provider's computed revenue model."""
    return get_success_data(client.get_revenue_model(provider_id, headers))


# -------------------------------------------------------------- enrollment


def create_enrollment(provider_id, client=api_client, **overrides):
    """Enroll a child at ``provider_id`` acting as that provider."""
    return get_success_data(
        client.create_enrollment(
            create_enrollment_payload(provider_id, **overrides),
            make_provider_headers(provider_id),
        )
    )


def withdraw_enrollment(enrollment_id, provider_id, exit_on, client=api_client):
    """The family leaves the home on ``exit_on``."""
    return get_success_data(
        client.withdraw_enrollment(
            enrollment_id, {"exit_on": exit_on}, make_provider_headers(provider_id)
        )
    )


def transfer_enrollment(enrollment_id, receiving_provider_id, transfer_on, client=api_client,
                        headers=NETWORK_ADMIN_HEADERS):
    """Place a transitioning child with another network home."""
    return get_success_data(
        client.transfer_enrollment(
            enrollment_id,
            {"receiving_provider_id": receiving_provider_id, "transfer_on": transfer_on},
            headers,
        )
    )


# --------------------------------------------------------- subsidy contract


def create_contract(provider_id, client=api_client, headers=NETWORK_ADMIN_HEADERS, **overrides):
    """Register a subsidy contract for ``provider_id``."""
    return get_success_data(
        client.create_contract(create_contract_payload(provider_id, **overrides), headers)
    )


def contract_version(contract_id, client=api_client, headers=NETWORK_ADMIN_HEADERS):
    """Re-read a contract's current version."""
    return get_success_data(client.get_contract(contract_id, headers))["version"]


def provider_with_contract(
    client=api_client,
    apply_overrides=None,
    verification_overrides=None,
    agreement_overrides=None,
    contract_overrides=None,
):
    """An ACTIVE home that also holds an ACTIVE subsidy contract."""
    ctx = active_provider(
        client, apply_overrides, verification_overrides, agreement_overrides
    )
    contract = create_contract(ctx["provider_id"], client, **(contract_overrides or {}))
    ctx["contract_id"] = contract["id"]
    ctx["contract"] = contract
    ctx["contract_version"] = contract["version"]
    return ctx


# ------------------------------------------------------------ subsidy claim


def create_claim(contract_id, provider_id, period_month, lines, expected_contract_version,
                 client=api_client):
    """Draft a monthly attendance claim."""
    return get_success_data(
        client.create_claim(
            create_claim_payload(contract_id, period_month, lines, expected_contract_version),
            make_provider_headers(provider_id),
        )
    )


def submit_claim(claim_id, provider_id, client=api_client):
    """Submit a drafted claim, computing the provisional advance valuation."""
    return get_success_data(
        client.submit_claim(claim_id, None, make_provider_headers(provider_id))
    )


def advance_claim(claim_id, client=api_client, headers=FISCAL_OFFICER_HEADERS):
    """Front eighty percent of the provisional amount."""
    return get_success_data(client.advance_claim(claim_id, None, headers))


def reconcile_claim(claim_id, client=api_client, headers=FISCAL_OFFICER_HEADERS):
    """Apply the agency's verified attendance."""
    return get_success_data(client.reconcile_claim(claim_id, None, headers))


def reject_claim(claim_id, rejection_reason, client=api_client, headers=FISCAL_OFFICER_HEADERS):
    """The agency vetoes a submitted claim."""
    return get_success_data(
        client.reject_claim(claim_id, {"rejection_reason": rejection_reason}, headers)
    )


def claim_walked_to(
    stage, contract_id, provider_id, period_month, lines, client=api_client
):
    """Draft a claim and walk it to ``stage``.

    ``stage`` is one of ``DRAFT``, ``SUBMITTED``, ``ADVANCE_PAID`` or
    ``RECONCILED``.
    """
    version = contract_version(contract_id, client)
    claim = create_claim(contract_id, provider_id, period_month, lines, version, client)
    if stage == "DRAFT":
        return claim
    claim = submit_claim(claim["id"], provider_id, client)
    if stage == "SUBMITTED":
        return claim
    claim = advance_claim(claim["id"], client)
    if stage == "ADVANCE_PAID":
        return claim
    return reconcile_claim(claim["id"], client)


# --------------------------------------------------------------- remittance


def post_remittance(contract_id, agency_reference, amount_cents, client=api_client,
                    headers=FISCAL_OFFICER_HEADERS, **overrides):
    """Post an agency payment and run the waterfall."""
    return get_success_data(
        client.create_remittance(
            create_remittance_payload(contract_id, agency_reference, amount_cents, **overrides),
            headers,
        )
    )


def reverse_remittance(remittance_id, reversal_reason, client=api_client,
                       headers=FISCAL_OFFICER_HEADERS):
    """Reverse a mis-posted agency payment."""
    return get_success_data(
        client.reverse_remittance(remittance_id, {"reversal_reason": reversal_reason}, headers)
    )


# --------------------------------------------------------- food program claim


def file_food_claim(provider_id, period_month, meal_lines, client=api_client):
    """File the monthly food program claim."""
    return get_success_data(
        client.create_food_claim(
            create_food_claim_payload(provider_id, period_month, meal_lines),
            make_provider_headers(provider_id),
        )
    )


def approve_food_claim(claim_id, disallowed_child_refs=None, client=api_client,
                       headers=FISCAL_OFFICER_HEADERS):
    """Approve the food program claim, optionally disallowing named children."""
    payload = None
    if disallowed_child_refs is not None:
        payload = {"disallowed_child_refs": list(disallowed_child_refs)}
    return get_success_data(client.approve_food_claim(claim_id, payload, headers))


# ---------------------------------------------------------------- substitute


def create_substitute(client=api_client, headers=NETWORK_ADMIN_HEADERS, **overrides):
    """Add a cleared member to the substitute pool."""
    return get_success_data(
        client.create_substitute(create_substitute_payload(**overrides), headers)
    )


def record_clearance(substitute_id, client=api_client, headers=NETWORK_ADMIN_HEADERS, **payload):
    """Record a clearance determination for a pool member."""
    return get_success_data(client.record_clearance(substitute_id, dict(payload), headers))


def request_coverage(provider_id, start_at, end_at, client=api_client, **overrides):
    """Request substitute coverage for a provider absence."""
    return get_success_data(
        client.create_assignment(
            create_assignment_payload(provider_id, start_at, end_at, **overrides),
            make_provider_headers(provider_id),
        )
    )


def accept_assignment(assignment_id, substitute_id, client=api_client):
    """The offered member accepts the coverage."""
    return get_success_data(
        client.accept_assignment(assignment_id, None, make_substitute_headers(substitute_id))
    )


def decline_assignment(assignment_id, substitute_id, client=api_client):
    """The offered member declines, and the selector re-runs."""
    return get_success_data(
        client.decline_assignment(assignment_id, None, make_substitute_headers(substitute_id))
    )


def complete_assignment(assignment_id, provider_id, client=api_client):
    """The provider confirms coverage was delivered, computing the cost."""
    return get_success_data(
        client.complete_assignment(assignment_id, None, make_provider_headers(provider_id))
    )


def invoice_assignment(assignment_id, client=api_client, headers=FISCAL_OFFICER_HEADERS):
    """Bill accrued coverage to the shared-services account."""
    return get_success_data(client.invoice_assignment(assignment_id, None, headers))


# ------------------------------------------------------------ coaching visit


def schedule_visit(provider_id, scheduled_on, client=api_client, headers=COACH_A_HEADERS,
                   **overrides):
    """Schedule a coaching visit."""
    return get_success_data(
        client.create_visit(create_visit_payload(provider_id, scheduled_on, **overrides), headers)
    )


def conduct_visit(visit_id, visit_conducted_on, observation_score, client=api_client,
                  headers=COACH_B_HEADERS, findings=None, **overrides):
    """Record the observation for a scheduled visit."""
    return get_success_data(
        client.conduct_visit(
            visit_id,
            conduct_visit_payload(
                visit_conducted_on, observation_score, findings=findings, **overrides
            ),
            headers,
        )
    )


def completed_visit(provider_id, on_date, observation_score, client=api_client,
                    scheduler=COACH_A_HEADERS, conductor=COACH_B_HEADERS, findings=None,
                    **overrides):
    """Schedule and conduct a visit on ``on_date`` with the clock moved there first."""
    visit = schedule_visit(provider_id, on_date, client, scheduler, **overrides)
    set_clock(on_date, client)
    return conduct_visit(
        visit["id"], on_date, observation_score, client, conductor, findings=findings
    )


# -------------------------------------------------------- compliance review


def open_review(provider_id, standard_codes, cap_due_on, client=api_client,
                headers=COACH_A_HEADERS, **overrides):
    """Open a scheduled compliance review."""
    return get_success_data(
        client.create_review(
            create_review_payload(provider_id, standard_codes, cap_due_on, **overrides), headers
        )
    )


def submit_cap(review_id, provider_id, cap_narrative, client=api_client):
    """The provider submits a corrective action plan."""
    return get_success_data(
        client.submit_cap(
            review_id, {"cap_narrative": cap_narrative}, make_provider_headers(provider_id)
        )
    )


def reject_cap(review_id, client=api_client, headers=COACH_B_HEADERS):
    """A coach rejects the corrective action plan."""
    return get_success_data(client.reject_cap(review_id, None, headers))


def close_review(review_id, client=api_client, headers=COACH_B_HEADERS):
    """A coach closes the review as compliant."""
    return get_success_data(client.close_review(review_id, None, headers))


def escalate_review(review_id, client=api_client, headers=NETWORK_ADMIN_HEADERS):
    """Escalate a repeatedly rejected plan to the licensing authority."""
    return get_success_data(client.escalate_review(review_id, None, headers))


def review_at_cap_rejected_twice(
    provider_id, standard_codes, cap_due_on, client=api_client, cap_narrative="Plan filed"
):
    """Open a review and run the CAP cycle until two rejections are recorded."""
    review = open_review(provider_id, standard_codes, cap_due_on, client)
    for _ in range(2):
        submit_cap(review["id"], provider_id, cap_narrative, client)
        review = reject_cap(review["id"], client)
    return review


# ---------------------------------------------------- group purchase order


def create_order(provider_id, lines, client=api_client, **overrides):
    """Open a group purchase order."""
    return get_success_data(
        client.create_order(
            create_order_payload(provider_id, lines, **overrides),
            make_provider_headers(provider_id),
        )
    )


def commit_order(order_id, provider_id, client=api_client):
    """Commit the order to the network buy."""
    return get_success_data(
        client.commit_order(order_id, None, make_provider_headers(provider_id))
    )


# ------------------------------------------------------------------ helpers


def subsidy_line(enrollment_id, attended_days, absent_days=0):
    """Shorthand for one attendance line."""
    return claim_line(enrollment_id, attended_days, absent_days)


EPOCH = CLOCK_EPOCH
