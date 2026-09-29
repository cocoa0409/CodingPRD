"""Composite setup helpers.

Nothing is seeded by the server, so every helper here drives the declared
endpoints to build the state a test needs.  Helpers are plain functions rather
than pytest fixtures so that a test can call them more than once with different
arguments; `test_suite/conftest.py` wraps the common ones.

`get_success_data` is used inside setup so that a setup step which the
implementation answers with a slightly different status still yields its row;
tests assert exact statuses themselves on the operation under test.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import DEFAULT_CLOCK, EVIDENCE_HASH_1
from .factories import (
    agreement_payload,
    agreement_response_payload,
    chargeback_payload,
    clearance_exception_payload,
    clock_payload,
    confirm_outcome_payload,
    distributor_payload,
    exception_decision_payload,
    exception_payload,
    notice_payload,
    observation_payload,
    policy_publish_payload,
    policy_review_decision_payload,
    pricing_policy_payload,
    product_payload,
    reseller_payload,
    serial_capture_payload,
    serial_unit_payload,
    ship_downstream_payload,
    supply_status_payload,
    test_purchase_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    BCM_HEADERS,
    COUNSEL_HEADERS,
    make_distributor_headers,
    make_reseller_headers,
)
from .types import (
    AgreementResponseDecision,
    Channel,
    ExceptionDecision,
    ReviewDecision,
    SupplyStatus,
    TestPurchaseOutcome,
)


# --------------------------------------------------------------------------- #
# Tier 1 — the logical clock
# --------------------------------------------------------------------------- #
def pin_clock(to_iso8601, headers=ADMIN_HEADERS):
    """Pin the logical clock and return the reported previous instant."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


# --------------------------------------------------------------------------- #
# Tier 1 — pricing policies along their state progression
# --------------------------------------------------------------------------- #
def create_draft_policy(**overrides):
    """A policy in DRAFT."""
    return get_success_data(
        api_client.create_pricing_policy(pricing_policy_payload(**overrides), BCM_HEADERS)
    )


def create_policy_in_review(**overrides):
    """A policy in IN_LEGAL_REVIEW."""
    policy = create_draft_policy(**overrides)
    return get_success_data(api_client.submit_policy_review(policy["id"], BCM_HEADERS))


def create_approved_policy(**overrides):
    """A policy in APPROVED, ready to publish."""
    policy = create_policy_in_review(**overrides)
    return get_success_data(
        api_client.decide_policy_review(
            policy["id"],
            policy_review_decision_payload(ReviewDecision.APPROVE_FOR_PUBLICATION.value),
            COUNSEL_HEADERS,
        )
    )


def create_published_policy(effective_from=DEFAULT_CLOCK, **overrides):
    """A policy in PUBLISHED with the supplied effective_from."""
    policy = create_approved_policy(**overrides)
    return get_success_data(
        api_client.publish_policy(
            policy["id"], policy_publish_payload(effective_from), COUNSEL_HEADERS
        )
    )


def create_withdrawn_policy(effective_from=DEFAULT_CLOCK, **overrides):
    """A policy in WITHDRAWN, still a governing candidate for past instants."""
    policy = create_published_policy(effective_from, **overrides)
    return get_success_data(
        api_client.withdraw_policy(
            policy["id"], {"withdrawn_reason": "Programme paused."}, COUNSEL_HEADERS
        )
    )


# --------------------------------------------------------------------------- #
# Tier 2 — products, distributors, resellers
# --------------------------------------------------------------------------- #
def create_product(policy_id, **overrides):
    return get_success_data(
        api_client.create_product(product_payload(policy_id, **overrides), BCM_HEADERS)
    )


def create_distributor(**overrides):
    return get_success_data(
        api_client.create_distributor(distributor_payload(**overrides), BCM_HEADERS)
    )


def create_reseller(**overrides):
    return get_success_data(api_client.create_reseller(reseller_payload(**overrides), BCM_HEADERS))


# --------------------------------------------------------------------------- #
# Tier 3 — the full agreement lifecycle up to an authorized reseller
# --------------------------------------------------------------------------- #
def create_sent_agreement(reseller_id, policy_id, **overrides):
    """An agreement in SENT with its reseller moved to PENDING_AGREEMENT."""
    agreement = get_success_data(
        api_client.create_agreement(
            agreement_payload(reseller_id, policy_id, **overrides), BCM_HEADERS
        )
    )
    return get_success_data(api_client.send_agreement(agreement["id"], BCM_HEADERS))


def create_countersigned_agreement(
    reseller_id, policy_id, non_negotiation_acknowledged=True, **overrides
):
    """An agreement in COUNTERSIGNED; the reseller stays on PENDING_AGREEMENT."""
    agreement = create_sent_agreement(reseller_id, policy_id, **overrides)
    return get_success_data(
        api_client.respond_agreement(
            agreement["id"],
            agreement_response_payload(
                AgreementResponseDecision.COUNTERSIGN.value,
                non_negotiation_acknowledged=non_negotiation_acknowledged,
            ),
            make_reseller_headers(reseller_id),
        )
    )


def create_active_agreement(reseller_id, policy_id, **overrides):
    """An ACTIVE agreement; the reseller becomes AUTHORIZED / OPEN / NONE."""
    agreement = create_countersigned_agreement(reseller_id, policy_id, **overrides)
    return get_success_data(api_client.activate_agreement(agreement["id"], BCM_HEADERS))


def create_authorized_reseller(policy_id, reseller_overrides=None, agreement_overrides=None):
    """A reseller carried all the way to AUTHORIZED with an ACTIVE agreement.

    Returns ``(reseller, agreement)`` with the reseller re-read after activation.
    """
    reseller = create_reseller(**(reseller_overrides or {}))
    agreement = create_active_agreement(
        reseller["id"], policy_id, **(agreement_overrides or {})
    )
    reseller = get_success_data(api_client.get_reseller(reseller["id"], BCM_HEADERS))
    return reseller, agreement


def bootstrap_authorized_channel(
    effective_from=DEFAULT_CLOCK,
    policy_overrides=None,
    product_overrides=None,
    reseller_overrides=None,
    agreement_overrides=None,
):
    """Published policy, product, distributor and one AUTHORIZED reseller.

    Returns a dict with keys ``policy``, ``product``, ``distributor``,
    ``reseller`` and ``agreement``.
    """
    policy = create_published_policy(effective_from, **(policy_overrides or {}))
    product = create_product(policy["id"], **(product_overrides or {}))
    distributor = create_distributor()
    reseller, agreement = create_authorized_reseller(
        policy["id"], reseller_overrides, agreement_overrides
    )
    return {
        "policy": policy,
        "product": product,
        "distributor": distributor,
        "reseller": reseller,
        "agreement": agreement,
    }


# --------------------------------------------------------------------------- #
# Tier 3 — evidence capture and evaluation
# --------------------------------------------------------------------------- #
def capture_observation(product_id, **overrides):
    """An observation in CAPTURED."""
    return get_success_data(
        api_client.create_observation(observation_payload(product_id, **overrides), ANALYST_HEADERS)
    )


def evaluate_observation(observation_id):
    """Evaluate a captured observation and return the evaluation response body."""
    return get_success_data(api_client.evaluate_observation(observation_id, ANALYST_HEADERS))


def create_detected_violation(
    product_id,
    reseller_id,
    listed_price_cents=8000,
    channel=Channel.MARKETPLACE.value,
    observed_at=None,
    evidence_hash=EVIDENCE_HASH_1,
    **observation_overrides,
):
    """Capture a below-floor listing and evaluate it into a DETECTED violation.

    Returns ``(violation, observation, evaluation)``.
    """
    payload_overrides = dict(observation_overrides)
    payload_overrides.update(
        {
            "channel": channel,
            "listed_price_cents": listed_price_cents,
            "matched_reseller_id": reseller_id,
            "evidence_hash": evidence_hash,
        }
    )
    if observed_at is not None:
        payload_overrides["observed_at"] = observed_at
    observation = capture_observation(product_id, **payload_overrides)
    evaluation = evaluate_observation(observation["id"])
    violation_id = evaluation.get("violation_id")
    violation = (
        get_success_data(api_client.get_violation(violation_id, BCM_HEADERS))
        if violation_id
        else None
    )
    return violation, observation, evaluation


def create_unmatched_breach(product_id, listed_price_cents=8000, **observation_overrides):
    """A below-floor listing with no matched reseller: no violation is opened.

    Returns ``(observation, evaluation)``.
    """
    observation = capture_observation(
        product_id, listed_price_cents=listed_price_cents, **observation_overrides
    )
    evaluation = evaluate_observation(observation["id"])
    return observation, evaluation


# --------------------------------------------------------------------------- #
# Tier 4 — notices and the points ledger
# --------------------------------------------------------------------------- #
def current_reseller_version(reseller_id):
    """The reseller's current version, for the mandatory OCC field."""
    return get_success_data(api_client.get_reseller(reseller_id, BCM_HEADERS))["version"]


def issue_notice(reseller_id, violation_id, headers=BCM_HEADERS, **overrides):
    """Issue a notice against a DETECTED violation at the computed rung."""
    payload = notice_payload(
        reseller_id, violation_id, current_reseller_version(reseller_id), **overrides
    )
    return get_success_data(api_client.issue_notice(payload, headers))


def issue_warning(product_id, reseller_id, listed_price_cents=14000, **observation_overrides):
    """Drive one breach all the way to an ISSUED notice.

    Returns ``(notice, violation)``.
    """
    violation, _observation, _evaluation = create_detected_violation(
        product_id, reseller_id, listed_price_cents=listed_price_cents, **observation_overrides
    )
    notice = issue_notice(reseller_id, violation["id"])
    return notice, violation


def issue_suspension(
    product_id,
    reseller_id,
    suspension_starts_at,
    suspension_ends_at,
    listed_price_cents=8000,
    headers=BCM_HEADERS,
    **observation_overrides,
):
    """Issue a notice supplying a suspension window.

    The caller is responsible for having accumulated enough points that the
    computed rung is SUSPENSION.
    """
    violation, _observation, _evaluation = create_detected_violation(
        product_id, reseller_id, listed_price_cents=listed_price_cents, **observation_overrides
    )
    notice = issue_notice(
        reseller_id,
        violation["id"],
        headers=headers,
        suspension_starts_at=suspension_starts_at,
        suspension_ends_at=suspension_ends_at,
    )
    return notice, violation


def acknowledge_notice(notice_id, reseller_id):
    return get_success_data(
        api_client.acknowledge_notice(notice_id, make_reseller_headers(reseller_id))
    )


def rescind_notice(notice_id, reason="Notice issued on incomplete evidence."):
    return get_success_data(
        api_client.rescind_notice(notice_id, {"rescinded_reason": reason}, COUNSEL_HEADERS)
    )


# --------------------------------------------------------------------------- #
# Tier 4 — pricing exceptions
# --------------------------------------------------------------------------- #
def request_exception(product_id, **overrides):
    """A pricing exception in REQUESTED."""
    return get_success_data(
        api_client.create_exception(exception_payload(product_id, **overrides), BCM_HEADERS)
    )


def approve_exception(exception_id, **overrides):
    """Approve a requested exception, installing its override floor."""
    return get_success_data(
        api_client.decide_exception(
            exception_id,
            exception_decision_payload(ExceptionDecision.APPROVE.value, **overrides),
            COUNSEL_HEADERS,
        )
    )


def create_approved_exception(product_id, **overrides):
    """A pricing exception in APPROVED with its floor snapshotted."""
    exception = request_exception(product_id, **overrides)
    return approve_exception(exception["id"])


def create_approved_clearance_exception(product_id, **overrides):
    """A CLEARANCE exception in APPROVED; the product must be in CLEARANCE."""
    exception = get_success_data(
        api_client.create_exception(
            clearance_exception_payload(product_id, **overrides), BCM_HEADERS
        )
    )
    return approve_exception(exception["id"])


# --------------------------------------------------------------------------- #
# Tier 4 — serialization, tracing and chargebacks
# --------------------------------------------------------------------------- #
def create_serial_unit(product_id, distributor_id, **overrides):
    """A unit in SHIPPED_TO_DISTRIBUTOR."""
    return get_success_data(
        api_client.create_serial_unit(
            serial_unit_payload(product_id, distributor_id, **overrides), BCM_HEADERS
        )
    )


def ship_unit_downstream(unit_id, distributor_id, reseller_id):
    """Move a unit SHIPPED_TO_DISTRIBUTOR -> SHIPPED_TO_RESELLER."""
    return get_success_data(
        api_client.ship_downstream(
            unit_id,
            ship_downstream_payload(reseller_id),
            make_distributor_headers(distributor_id),
        )
    )


def order_test_purchase(observation_id, **overrides):
    """A test purchase in ORDERED."""
    return get_success_data(
        api_client.create_test_purchase(
            test_purchase_payload(observation_id, **overrides), ANALYST_HEADERS
        )
    )


def capture_purchase_serial(test_purchase_id, serial_number):
    """Move a test purchase ORDERED -> SERIAL_CAPTURED."""
    return get_success_data(
        api_client.capture_serial(
            test_purchase_id, serial_capture_payload(serial_number), ANALYST_HEADERS
        )
    )


def confirm_unauthorized(test_purchase_id, **overrides):
    """Move a test purchase SERIAL_CAPTURED -> CONFIRMED_UNAUTHORIZED."""
    return get_success_data(
        api_client.confirm_outcome(
            test_purchase_id,
            confirm_outcome_payload(TestPurchaseOutcome.UNAUTHORIZED.value, **overrides),
            ANALYST_HEADERS,
        )
    )


def create_confirmed_trace(
    product_id, distributor_id, observation_id=None, downstream_reseller_id=None, **unit_overrides
):
    """Register a unit, trace it through a test purchase and confirm the finding.

    Returns ``(purchase, unit, observation)``.  When ``observation_id`` is
    omitted a fresh unmatched observation is captured to hang the purchase on.
    """
    unit = create_serial_unit(product_id, distributor_id, **unit_overrides)
    if downstream_reseller_id is not None:
        unit = ship_unit_downstream(unit["id"], distributor_id, downstream_reseller_id)
    if observation_id is None:
        observation = capture_observation(product_id, listed_price_cents=8000)
        observation_id = observation["id"]
    else:
        observation = get_success_data(api_client.get_observation(observation_id, BCM_HEADERS))
    purchase = order_test_purchase(observation_id)
    capture_purchase_serial(purchase["id"], unit["serial_number"])
    purchase = confirm_unauthorized(purchase["id"])
    return purchase, unit, observation


def current_distributor_version(distributor_id):
    """The distributor's current version, for the mandatory OCC field."""
    return get_success_data(api_client.get_distributor(distributor_id, BCM_HEADERS))["version"]


def assess_chargeback(distributor_id, test_purchase_id, diverted_units=1, **overrides):
    """Assess a chargeback using the distributor's current version."""
    payload = chargeback_payload(
        distributor_id,
        test_purchase_id,
        current_distributor_version(distributor_id),
        diverted_units,
        **overrides,
    )
    return get_success_data(api_client.assess_chargeback(payload, BCM_HEADERS))


def create_assessed_chargeback(product_id, distributor_id, diverted_units=1, **unit_overrides):
    """Trace a unit and assess a chargeback against its shipping distributor.

    Returns ``(chargeback, purchase, unit)``.
    """
    purchase, unit, _observation = create_confirmed_trace(
        product_id, distributor_id, **unit_overrides
    )
    chargeback = assess_chargeback(distributor_id, purchase["id"], diverted_units)
    return chargeback, purchase, unit


# --------------------------------------------------------------------------- #
# Tier 5 — sweeps and terminal states
# --------------------------------------------------------------------------- #
def run_sweep(headers=BCM_HEADERS):
    """Realize every time-driven consequence due at the current clock."""
    return get_success_data(api_client.run_sweep(headers))


def hold_supply(reseller_id, hold_reason="QUALITY_OBLIGATION"):
    """Move an OPEN reseller to HOLD on the supply axis only."""
    return get_success_data(
        api_client.set_supply_status(
            reseller_id,
            supply_status_payload(SupplyStatus.HOLD.value, hold_reason=hold_reason),
            BCM_HEADERS,
        )
    )


def release_supply(reseller_id):
    """Move a HOLD reseller back to OPEN with hold_reason NONE."""
    return get_success_data(
        api_client.set_supply_status(
            reseller_id, supply_status_payload(SupplyStatus.OPEN.value), BCM_HEADERS
        )
    )


def read_reseller(reseller_id, headers=BCM_HEADERS):
    return validate_success(api_client.get_reseller(reseller_id, headers))


def read_distributor(distributor_id, headers=BCM_HEADERS):
    return validate_success(api_client.get_distributor(distributor_id, headers))


def read_product(product_id, headers=BCM_HEADERS):
    return validate_success(api_client.get_product(product_id, headers))


def read_violation(violation_id, headers=BCM_HEADERS):
    return validate_success(api_client.get_violation(violation_id, headers))


def read_notice(notice_id, headers=BCM_HEADERS):
    return validate_success(api_client.get_notice(notice_id, headers))


def read_agreement(agreement_id, headers=BCM_HEADERS):
    return validate_success(api_client.get_agreement(agreement_id, headers))


def read_exception(exception_id, headers=BCM_HEADERS):
    return validate_success(api_client.get_exception(exception_id, headers))


def read_serial_unit(unit_id, headers=BCM_HEADERS):
    return validate_success(api_client.get_serial_unit(unit_id, headers))


def read_test_purchase(purchase_id, headers=BCM_HEADERS):
    return validate_success(api_client.get_test_purchase(purchase_id, headers))


def read_chargeback(chargeback_id, headers=BCM_HEADERS):
    return validate_success(api_client.get_chargeback(chargeback_id, headers))


def read_policy(policy_id, headers=BCM_HEADERS):
    return validate_success(api_client.get_pricing_policy(policy_id, headers))


def read_observation(observation_id, headers=BCM_HEADERS):
    return validate_success(api_client.get_observation(observation_id, headers))


def read_compliance_summary(reseller_id, headers=BCM_HEADERS, params=None):
    return validate_success(api_client.get_compliance_summary(reseller_id, headers, params=params))


def read_effective_floor(product_id, headers=BCM_HEADERS, **params):
    return validate_success(api_client.get_effective_floor(product_id, headers, params=params))


def read_exposure(distributor_id, variant, headers=BCM_HEADERS, **params):
    params = dict(params)
    params["variant"] = variant
    return validate_success(
        api_client.get_diversion_exposure(distributor_id, headers, params=params)
    )
