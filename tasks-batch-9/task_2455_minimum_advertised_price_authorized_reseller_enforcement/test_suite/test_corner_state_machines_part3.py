"""Doors that stay shut: terminal states, undeclared transitions and guards.

Each entity's terminal states are checked by attempting the transition that
would move them; each declared transition is checked from a state it is not
declared from; and the preconditions that are not state checks at all — the
antitrust guardrail on countersignature, the suspension supply lock, the dispute
cap, the cure window and the two ownership rules — are checked from a live
state where only that guard can fire.  The last two groups check the side
effects an operation must execute and the operations that must be no-ops.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ANALYST_HEADERS,
    BCM_HEADERS,
    COUNSEL_HEADERS,
    api_client,
)
from test_helpers.assertions import (
    assert_same_instant,
    score_delta,
    tier_rate_for_score,
    violation_points,
)
from test_helpers.constants import evidence_hash
from test_helpers.factories import (
    agreement_payload,
    agreement_response_payload,
    chargeback_dispute_decision_payload,
    chargeback_dispute_payload,
    confirm_outcome_payload,
    cure_submission_payload,
    exception_decision_payload,
    notice_payload,
    policy_publish_payload,
    policy_review_decision_payload,
    serial_capture_payload,
    ship_downstream_payload,
    supply_status_payload,
    violation_dispute_decision_payload,
    violation_dispute_payload,
)
from test_helpers.fixtures import (
    approve_exception,
    assess_chargeback,
    capture_observation,
    capture_purchase_serial,
    create_active_agreement,
    create_approved_policy,
    create_confirmed_trace,
    create_detected_violation,
    create_distributor,
    create_draft_policy,
    create_product,
    create_published_policy,
    create_reseller,
    create_sent_agreement,
    create_serial_unit,
    create_withdrawn_policy,
    current_reseller_version,
    evaluate_observation,
    issue_notice,
    order_test_purchase,
    pin_clock,
    read_chargeback,
    read_distributor,
    read_exception,
    read_notice,
    read_observation,
    read_policy,
    read_product,
    read_reseller,
    read_serial_unit,
    read_test_purchase,
    read_violation,
    request_exception,
    run_sweep,
    ship_unit_downstream,
)
from test_helpers.test_users import make_distributor_headers, make_reseller_headers

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
CLOCK_AUG_31 = "2026-08-31T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
OBSERVED_AUG_19 = "2026-08-19T00:00:00Z"
TERM_ENDS_JUN_30_2027 = "2027-06-30T00:00:00Z"
SUSPENSION_STARTS = "2026-09-01T00:00:00Z"
SUSPENSION_ENDS = "2026-09-10T00:00:00Z"
EXCEPTION_STARTS = "2026-08-10T00:00:00Z"
EXCEPTION_ENDS = "2026-08-25T00:00:00Z"
DEFAULT_CHANNELS = ["MARKETPLACE", "OWN_WEBSITE"]


# --------------------------------------------------------------------------- #
# Shared setup
# --------------------------------------------------------------------------- #
def _authorized_channel(permitted_channels=None):
    """A published policy, a product at a 15000 floor and an AUTHORIZED reseller."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    product = create_product(policy["id"], name="Studio Headphones")
    reseller = create_reseller(legal_name="Acme Retail LLC", contact_email="ops@acme.example")
    agreement = create_active_agreement(
        reseller["id"],
        policy["id"],
        permitted_channels=list(permitted_channels or DEFAULT_CHANNELS),
        quality_obligations=["AUTHENTICITY_LABELING"],
        term_ends_at=TERM_ENDS_JUN_30_2027,
    )
    return {"policy": policy, "product": product, "reseller": reseller, "agreement": agreement}


def _warned(world):
    """One 14000 marketplace listing carried to an ISSUED warning notice."""
    pin_clock(CLOCK_AUG_20)
    violation, observation, _evaluation = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=evidence_hash(0),
        listing_url="https://marketplace.example/acme/1",
        seller_display_name="Acme Store",
    )
    notice = issue_notice(world["reseller"]["id"], violation["id"])
    world["violation"] = violation
    world["observation"] = observation
    world["notice"] = notice
    world["violations"] = [violation]
    world["notices"] = [notice]
    return world


def _ladder_to_suspension(world):
    """A warning on a 14000 listing, then a suspension on a 9000 listing."""
    _warned(world)
    second, _obs, _ev = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=evidence_hash(1),
        listing_url="https://marketplace.example/acme/2",
        seller_display_name="Acme Store",
    )
    suspension = issue_notice(
        world["reseller"]["id"],
        second["id"],
        suspension_starts_at=SUSPENSION_STARTS,
        suspension_ends_at=SUSPENSION_ENDS,
    )
    world["violations"].append(second)
    world["notices"].append(suspension)
    return world


def _terminate(world):
    """The third rung: counsel issues the termination the ladder now computes."""
    third, _obs, _ev = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_19,
        evidence_hash=evidence_hash(2),
        listing_url="https://marketplace.example/acme/3",
        seller_display_name="Acme Store",
    )
    notice = issue_notice(
        world["reseller"]["id"],
        third["id"],
        headers=COUNSEL_HEADERS,
        delivery_channel="CERTIFIED_MAIL",
    )
    world["violations"].append(third)
    world["notices"].append(notice)
    return notice


def _grey_listing(product_id, listed_price_cents=9000, index=3, suffix="1"):
    """A below-floor listing that could not be matched to any authorized reseller."""
    return capture_observation(
        product_id,
        listed_price_cents=listed_price_cents,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=evidence_hash(index),
        seller_display_name="GreyBox Deals",
        listing_url=f"https://marketplace.example/greybox/{suffix}",
    )


def _requested_exception(product_id, **overrides):
    """A PROMOTIONAL_EVENT exception requested over 10 to 25 August at 13000."""
    payload = dict(
        exception_type="PROMOTIONAL_EVENT",
        starts_at=EXCEPTION_STARTS,
        ends_at=EXCEPTION_ENDS,
        requested_override_floor_cents=13000,
        dealer_input_source="BRAND_MARKETING_PLAN",
    )
    payload.update(overrides)
    return request_exception(product_id, **payload)


def _captured_purchase(product_id, distributor_id, index=3, suffix="1"):
    """A test purchase in SERIAL_CAPTURED against a registered unit."""
    unit = create_serial_unit(product_id, distributor_id, lot_code="LOT-A")
    pin_clock(CLOCK_AUG_20)
    observation = _grey_listing(product_id, index=index, suffix=suffix)
    purchase = order_test_purchase(observation["id"], ordered_at=OBSERVED_AUG_19)
    purchase = capture_purchase_serial(purchase["id"], unit["serial_number"])
    return purchase, unit, observation


def _assessed_chargeback(diverted_units=4, reseller_overrides=None):
    """A four-unit chargeback against the distributor that shipped the traced unit."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    product = create_product(policy["id"], name="Studio Headphones")
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    reseller = None
    if reseller_overrides is not None:
        reseller = create_reseller(
            sourcing_distributor_id=distributor["id"], **reseller_overrides
        )
    purchase, unit, _observation = create_confirmed_trace(
        product["id"], distributor["id"], lot_code="LOT-A"
    )
    chargeback = assess_chargeback(distributor["id"], purchase["id"], diverted_units=diverted_units)
    return {
        "product": product,
        "distributor": distributor,
        "reseller": reseller,
        "purchase": purchase,
        "unit": unit,
        "chargeback": chargeback,
    }


# --------------------------------------------------------------------------- #
# Terminal-state lockdown
# --------------------------------------------------------------------------- #
def test_policy_withdrawn_is_terminal_and_further_publish_rejected():
    """A withdrawn policy cannot be published back into force.

    PRD: "`SUPERSEDED` and `WITHDRAWN` are the two terminal states of a policy document;
    nothing moves out of them."

    Design: Corner/state_machines/policy_withdrawn_is_terminal_and_further_publish_rejected
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_withdrawn_policy(CLOCK_AUG_01)
    assert policy["status"] == "WITHDRAWN"

    validate_error(
        api_client.publish_policy(
            policy["id"], policy_publish_payload(CLOCK_AUG_01), COUNSEL_HEADERS
        ),
        "ERR_INVALID_STATE",
    )

    assert read_policy(policy["id"])["status"] == "WITHDRAWN"


def test_agreement_declined_is_terminal_and_activate_rejected():
    """A declined agreement is dead; activation cannot resurrect it.

    PRD: "`DECLINED`, `TERMINATED` and `EXPIRED` are the three terminal states of an
    agreement."

    Design: Corner/state_machines/agreement_declined_is_terminal_and_activate_rejected
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    reseller = create_reseller(legal_name="Acme Retail LLC")
    agreement = create_sent_agreement(reseller["id"], policy["id"])
    declined = validate_success(
        api_client.respond_agreement(
            agreement["id"],
            agreement_response_payload("DECLINE", decline_reason="Channel terms unacceptable."),
            make_reseller_headers(reseller["id"]),
        )
    )
    assert declined["status"] == "DECLINED"

    validate_error(
        api_client.activate_agreement(agreement["id"], BCM_HEADERS), "ERR_INVALID_STATE"
    )

    assert read_reseller(reseller["id"])["authorization_status"] == "APPLIED"


def test_violation_voided_is_terminal_and_cure_submission_rejected():
    """There is nothing left to cure once the dispute was sustained.

    PRD: "`CURED`, `ESCALATED`, `VOIDED` and `CLOSED_MOOT` are the four terminal states of
    a violation."

    Design: Corner/state_machines/violation_voided_is_terminal_and_cure_submission_rejected
    """
    world = _warned(_authorized_channel())
    reseller_headers = make_reseller_headers(world["reseller"]["id"])
    validate_success(
        api_client.dispute_violation(
            world["violation"]["id"], violation_dispute_payload(), reseller_headers
        )
    )
    validate_success(
        api_client.decide_violation_dispute(
            world["violation"]["id"],
            violation_dispute_decision_payload("SUSTAIN"),
            BCM_HEADERS,
        )
    )
    assert read_violation(world["violation"]["id"])["status"] == "VOIDED"

    validate_error(
        api_client.submit_cure(
            world["violation"]["id"], cure_submission_payload(), reseller_headers
        ),
        "ERR_INVALID_STATE",
    )

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "VOIDED"
    assert violation["resolution_reason"] == "DISPUTE_SUSTAINED"


def test_notice_rescinded_is_terminal_and_acknowledge_rejected():
    """A rescinded notice cannot be acknowledged after the fact.

    PRD: "`SATISFIED` and `RESCINDED` are the two terminal states of a notice."

    Design: Corner/state_machines/notice_rescinded_is_terminal_and_acknowledge_rejected
    """
    world = _warned(_authorized_channel())
    rescinded = validate_success(
        api_client.rescind_notice(
            world["notice"]["id"],
            {"rescinded_reason": "Issued on incomplete evidence."},
            COUNSEL_HEADERS,
        )
    )
    assert rescinded["status"] == "RESCINDED"

    validate_error(
        api_client.acknowledge_notice(
            world["notice"]["id"], make_reseller_headers(world["reseller"]["id"])
        ),
        "ERR_INVALID_STATE",
    )

    notice = read_notice(world["notice"]["id"])
    assert notice["status"] == "RESCINDED"
    assert notice["acknowledged_at"] is None


def test_exception_rejected_is_terminal_and_second_decision_rejected():
    """A rejected exception cannot be re-decided into an approval.

    PRD: "`BrandLegalCounsel` decides a requested exception, supplying a `decision` and a
    `decision_reason`, and the exception must be in `REQUESTED` for either branch to
    apply."

    Design: Corner/state_machines/exception_rejected_is_terminal_and_second_decision_rejected
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    product = create_product(policy["id"], name="Studio Headphones")
    exception = _requested_exception(product["id"])
    rejected = validate_success(
        api_client.decide_exception(
            exception["id"],
            exception_decision_payload("REJECT", decision_reason="No rationale."),
            COUNSEL_HEADERS,
        )
    )
    assert rejected["status"] == "REJECTED"

    validate_error(
        api_client.decide_exception(
            exception["id"],
            exception_decision_payload("APPROVE", decision_reason="Reconsidered."),
            COUNSEL_HEADERS,
        ),
        "ERR_INVALID_STATE",
    )

    row = read_exception(exception["id"])
    assert row["status"] == "REJECTED"
    assert row["override_floor_cents"] is None
    assert read_product(product["id"])["open_exception_count"] == 0


def test_test_purchase_cleared_is_terminal_and_second_confirm_outcome_rejected():
    """A cleared purchase cannot be re-confirmed as unauthorized.

    PRD: "The analyst then confirms the finding, supplying an `outcome` and an
    `outcome_reason`, on a purchase that must be in `SERIAL_CAPTURED`."

    Design: Corner/state_machines/test_purchase_cleared_is_terminal_and_second_confirm_outcome_rejected
    """
    world = _authorized_channel()
    distributor = create_distributor(legal_name="Northwind Distribution")
    purchase, unit, observation = _captured_purchase(world["product"]["id"], distributor["id"])
    cleared = validate_success(
        api_client.confirm_outcome(
            purchase["id"], confirm_outcome_payload("AUTHORIZED"), ANALYST_HEADERS
        )
    )
    assert cleared["status"] == "CLEARED"

    validate_error(
        api_client.confirm_outcome(
            purchase["id"], confirm_outcome_payload("UNAUTHORIZED"), ANALYST_HEADERS
        ),
        "ERR_INVALID_STATE",
    )

    assert read_test_purchase(purchase["id"])["status"] == "CLEARED"
    assert read_serial_unit(unit["id"])["status"] == "SHIPPED_TO_DISTRIBUTOR"
    assert read_observation(observation["id"])["unauthorized_seller_confirmed"] is False


def test_chargeback_reversed_is_terminal_and_further_dispute_rejected():
    """A reversed chargeback is closed for good, with dispute rounds still unspent.

    PRD: "Supplying a `dispute_reason` moves a chargeback `ASSESSED → DISPUTED` or
    `UPHELD → DISPUTED`, recording that reason and advancing the chargeback's `version`;
    it requires the chargeback to be in `ASSESSED` or `UPHELD`, requires `dispute_rounds`
    to be strictly below 2 (else `ERR_DISPUTE_ROUNDS_EXHAUSTED`), and requires the acting
    distributor's `X-User-ID` to equal the chargeback's `distributor_id`."

    Design: Corner/state_machines/chargeback_reversed_is_terminal_and_further_dispute_rejected
    """
    world = _assessed_chargeback()
    distributor_headers = make_distributor_headers(world["distributor"]["id"])
    validate_success(
        api_client.dispute_chargeback(
            world["chargeback"]["id"], chargeback_dispute_payload(), distributor_headers
        )
    )
    reversed_row = validate_success(
        api_client.decide_chargeback_dispute(
            world["chargeback"]["id"],
            chargeback_dispute_decision_payload("REVERSE"),
            COUNSEL_HEADERS,
        )
    )
    assert reversed_row["status"] == "REVERSED"
    assert reversed_row["dispute_rounds"] == 0

    validate_error(
        api_client.dispute_chargeback(
            world["chargeback"]["id"], chargeback_dispute_payload(), distributor_headers
        ),
        "ERR_INVALID_STATE",
    )

    assert read_chargeback(world["chargeback"]["id"])["status"] == "REVERSED"
    assert read_distributor(world["distributor"]["id"])["chargeback_balance_cents"] == 0


def test_serial_unit_recalled_is_terminal_and_ship_downstream_rejected():
    """Recalled stock cannot be shipped on to a healthy reseller.

    PRD: "A serialized unit reaches `RECALLED` only through the agreement-termination
    cascade of §3.4, and `RECALLED` is its single terminal state."

    Design: Corner/state_machines/serial_unit_recalled_is_terminal_and_ship_downstream_rejected
    """
    world = _authorized_channel()
    distributor = create_distributor(legal_name="Northwind Distribution")
    unit = create_serial_unit(world["product"]["id"], distributor["id"], lot_code="LOT-A")
    ship_unit_downstream(unit["id"], distributor["id"], world["reseller"]["id"])
    healthy = create_reseller(legal_name="Beta Retail LLC")
    create_active_agreement(healthy["id"], world["policy"]["id"])
    assert read_reseller(healthy["id"])["supply_status"] == "OPEN"

    _ladder_to_suspension(world)
    _terminate(world)
    assert read_serial_unit(unit["id"])["status"] == "RECALLED"

    validate_error(
        api_client.ship_downstream(
            unit["id"],
            ship_downstream_payload(healthy["id"]),
            make_distributor_headers(distributor["id"]),
        ),
        "ERR_INVALID_STATE",
    )

    recalled = read_serial_unit(unit["id"])
    assert recalled["status"] == "RECALLED"
    assert recalled["downstream_reseller_id"] == world["reseller"]["id"]


def test_observation_evaluated_is_terminal_and_second_evaluate_rejected():
    """Evaluation happens once, and the second attempt has its own dedicated code.

    PRD: "It requires `evaluation_status` to be `CAPTURED` — a second attempt on an
    already-evaluated row is rejected with `ERR_ALREADY_EVALUATED` — and it requires a
    governing policy to exist for `observed_at` in the sense of §3.1, with the selected
    policy being one whose status is `PUBLISHED`, `SUPERSEDED` or `WITHDRAWN` and whose
    `effective_from` is at or before `observed_at`; otherwise `ERR_NO_GOVERNING_POLICY`."

    Design: Corner/state_machines/observation_evaluated_is_terminal_and_second_evaluate_rejected
    """
    world = _authorized_channel()
    pin_clock(CLOCK_AUG_20)
    observation = _grey_listing(world["product"]["id"])
    evaluate_observation(observation["id"])
    assert read_observation(observation["id"])["evaluation_status"] == "EVALUATED_BREACH"

    validate_error(
        api_client.evaluate_observation(observation["id"], ANALYST_HEADERS),
        "ERR_ALREADY_EVALUATED",
    )

    assert read_observation(observation["id"])["version"] == 2


# --------------------------------------------------------------------------- #
# Undeclared transitions
# --------------------------------------------------------------------------- #
def test_policy_submit_review_from_published_rejected():
    """Only a draft may be handed to counsel.

    PRD: "It requires the policy to be in `DRAFT`, and it re-checks that
    `termination_points_threshold` is strictly greater than `suspension_points_threshold`
    — a draft whose ladder thresholds have been edited into an incoherent order cannot be
    handed to counsel."

    Design: Corner/state_machines/policy_submit_review_from_published_rejected
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)

    validate_error(
        api_client.submit_policy_review(policy["id"], BCM_HEADERS), "ERR_INVALID_STATE"
    )

    row = read_policy(policy["id"])
    assert row["status"] == "PUBLISHED"
    assert row["revision_number"] == 1


def test_policy_review_decision_from_draft_rejected():
    """Counsel cannot approve a document that was never submitted.

    PRD: "Both branches require the document to be in `IN_LEGAL_REVIEW`."

    Design: Corner/state_machines/policy_review_decision_from_draft_rejected
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_draft_policy()

    validate_error(
        api_client.decide_policy_review(
            policy["id"],
            policy_review_decision_payload("APPROVE_FOR_PUBLICATION"),
            COUNSEL_HEADERS,
        ),
        "ERR_INVALID_STATE",
    )

    row = read_policy(policy["id"])
    assert row["status"] == "DRAFT"
    assert row["reviewed_by_user_id"] is None


def test_agreement_respond_from_draft_before_send_rejected():
    """A reseller cannot countersign a document the brand has not sent.

    PRD: "It requires the agreement to be `SENT` and the reseller's
    `authorization_status` to be `PENDING_AGREEMENT`, and it requires the request to omit
    `counter_price_proposal_cents` entirely — supplying it at all is the antitrust
    rejection of §2.7."

    Design: Corner/state_machines/agreement_respond_from_draft_before_send_rejected
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    reseller = create_reseller(legal_name="Acme Retail LLC")
    agreement = validate_success(
        api_client.create_agreement(agreement_payload(reseller["id"], policy["id"]), BCM_HEADERS),
        201,
    )
    assert agreement["status"] == "DRAFT"

    validate_error(
        api_client.respond_agreement(
            agreement["id"],
            agreement_response_payload("COUNTERSIGN"),
            make_reseller_headers(reseller["id"]),
        ),
        "ERR_INVALID_STATE",
    )

    assert read_reseller(reseller["id"])["authorization_status"] == "APPLIED"


def test_agreement_activate_from_sent_rejected():
    """Activation is declared only from COUNTERSIGNED.

    PRD: "It requires the agreement to be `COUNTERSIGNED`, requires the referenced policy
    to still be in status `PUBLISHED`, and — when that policy has
    `non_negotiation_ack_required` set to true — requires `non_negotiation_acknowledged`
    on the agreement to be true, else the activation is rejected with
    `ERR_NON_NEGOTIATION_ACK_MISSING`."

    Design: Corner/state_machines/agreement_activate_from_sent_rejected
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    reseller = create_reseller(legal_name="Acme Retail LLC")
    agreement = create_sent_agreement(reseller["id"], policy["id"])
    assert agreement["status"] == "SENT"

    validate_error(
        api_client.activate_agreement(agreement["id"], BCM_HEADERS), "ERR_INVALID_STATE"
    )

    reseller_row = read_reseller(reseller["id"])
    assert reseller_row["authorization_status"] == "PENDING_AGREEMENT"
    assert reseller_row["supply_status"] == "HOLD"


def test_notice_issuance_for_a_cured_violation_rejected():
    """A cured violation is no longer noticeable, and says so in its own code.

    PRD: "The violation must be in status `DETECTED`, else
    `ERR_VIOLATION_NOT_NOTICEABLE`."

    Design: Corner/state_machines/notice_issuance_for_a_cured_violation_rejected
    """
    world = _warned(_authorized_channel())
    validate_success(
        api_client.submit_cure(
            world["violation"]["id"],
            cure_submission_payload(),
            make_reseller_headers(world["reseller"]["id"]),
        )
    )
    assert read_violation(world["violation"]["id"])["status"] == "CURED"

    validate_error(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                world["violation"]["id"],
                current_reseller_version(world["reseller"]["id"]),
            ),
            BCM_HEADERS,
        ),
        "ERR_VIOLATION_NOT_NOTICEABLE",
    )

    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 3


def test_violation_dispute_from_detected_rejected():
    """A violation nobody has been noticed for cannot be disputed.

    PRD: "Supplying a `dispute_reason` moves the violation `NOTICED → DISPUTED`, recording
    that reason and advancing the violation's `version`; it requires the violation to be
    `NOTICED` and requires `dispute_rounds` to be strictly below 2, else
    `ERR_DISPUTE_ROUNDS_EXHAUSTED`."

    Design: Corner/state_machines/violation_dispute_from_detected_rejected
    """
    world = _authorized_channel()
    pin_clock(CLOCK_AUG_20)
    violation, _observation, _evaluation = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        seller_display_name="Acme Store",
    )
    assert violation["status"] == "DETECTED"

    validate_error(
        api_client.dispute_violation(
            violation["id"],
            violation_dispute_payload(),
            make_reseller_headers(world["reseller"]["id"]),
        ),
        "ERR_INVALID_STATE",
    )

    row = read_violation(violation["id"])
    assert row["status"] == "DETECTED"
    assert row["dispute_rounds"] == 0


def test_violation_dispute_decision_from_noticed_rejected():
    """The brand cannot decide a dispute the reseller never opened.

    PRD: "A `BrandChannelManager` then decides the dispute with a `decision` and a
    `decision_reason`, on a violation that must be in `DISPUTED`."

    Design: Corner/state_machines/violation_dispute_decision_from_noticed_rejected
    """
    world = _warned(_authorized_channel())
    assert read_violation(world["violation"]["id"])["status"] == "NOTICED"

    validate_error(
        api_client.decide_violation_dispute(
            world["violation"]["id"],
            violation_dispute_decision_payload("REJECT"),
            BCM_HEADERS,
        ),
        "ERR_INVALID_STATE",
    )

    row = read_violation(world["violation"]["id"])
    assert row["status"] == "NOTICED"
    assert row["dispute_rounds"] == 0
    assert row["assessed_points"] == 3


def test_test_purchase_confirm_outcome_from_ordered_rejected():
    """The finding cannot be confirmed before the serial is read off the carton.

    PRD: "The analyst then confirms the finding, supplying an `outcome` and an
    `outcome_reason`, on a purchase that must be in `SERIAL_CAPTURED`."

    Design: Corner/state_machines/test_purchase_confirm_outcome_from_ordered_rejected
    """
    world = _authorized_channel()
    pin_clock(CLOCK_AUG_20)
    observation = _grey_listing(world["product"]["id"])
    purchase = order_test_purchase(observation["id"], ordered_at=OBSERVED_AUG_19)
    assert purchase["status"] == "ORDERED"

    validate_error(
        api_client.confirm_outcome(
            purchase["id"], confirm_outcome_payload("UNAUTHORIZED"), ANALYST_HEADERS
        ),
        "ERR_INVALID_STATE",
    )

    row = read_test_purchase(purchase["id"])
    assert row["status"] == "ORDERED"
    assert row["traced_serial_unit_id"] is None


def test_chargeback_dispute_decision_from_assessed_rejected():
    """Counsel decides disputes, not assessments.

    PRD: "`BrandLegalCounsel` then decides, supplying a `decision` and a
    `decision_reason`, on a chargeback that must be in `DISPUTED`."

    Design: Corner/state_machines/chargeback_dispute_decision_from_assessed_rejected
    """
    world = _assessed_chargeback()
    assert world["chargeback"]["status"] == "ASSESSED"

    validate_error(
        api_client.decide_chargeback_dispute(
            world["chargeback"]["id"],
            chargeback_dispute_decision_payload("UPHOLD"),
            COUNSEL_HEADERS,
        ),
        "ERR_INVALID_STATE",
    )

    row = read_chargeback(world["chargeback"]["id"])
    assert row["status"] == "ASSESSED"
    assert row["dispute_rounds"] == 0
    assert read_distributor(world["distributor"]["id"])["chargeback_balance_cents"] == 10000


def test_serial_capture_from_serial_captured_rejected():
    """A second serial cannot be recorded against the same purchase.

    PRD: "The purchase must be in `ORDERED`."

    Design: Corner/state_machines/serial_capture_from_serial_captured_rejected
    """
    world = _authorized_channel()
    distributor = create_distributor(legal_name="Northwind Distribution")
    purchase, unit, _observation = _captured_purchase(world["product"]["id"], distributor["id"])
    other_unit = create_serial_unit(world["product"]["id"], distributor["id"], lot_code="LOT-B")
    assert purchase["status"] == "SERIAL_CAPTURED"

    validate_error(
        api_client.capture_serial(
            purchase["id"], serial_capture_payload(other_unit["serial_number"]), ANALYST_HEADERS
        ),
        "ERR_INVALID_STATE",
    )

    row = read_test_purchase(purchase["id"])
    assert row["status"] == "SERIAL_CAPTURED"
    assert row["captured_serial_number"] == unit["serial_number"]
    assert row["traced_serial_unit_id"] == unit["id"]


# --------------------------------------------------------------------------- #
# Preconditions that are not state checks
# --------------------------------------------------------------------------- #
def test_agreement_countersign_with_counter_price_proposal_rejected():
    """A countersignature carrying a price counter-proposal is an antitrust failure.

    PRD: "A reseller's response to an agreement may not carry a price counter-proposal:
    if the response supplies `counter_price_proposal_cents` at all, it is rejected with
    `ERR_ANTITRUST_NEGOTIATION_PROHIBITED` (HTTP 422), because entertaining a
    counter-proposal is exactly the negotiation the unilateral posture forbids."

    Design: Corner/state_machines/agreement_countersign_with_counter_price_proposal_rejected
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    reseller = create_reseller(legal_name="Acme Retail LLC")
    agreement = create_sent_agreement(reseller["id"], policy["id"])

    validate_error(
        api_client.respond_agreement(
            agreement["id"],
            agreement_response_payload("COUNTERSIGN", counter_price_proposal_cents=14000),
            make_reseller_headers(reseller["id"]),
        ),
        "ERR_ANTITRUST_NEGOTIATION_PROHIBITED",
    )

    row = validate_success(api_client.get_agreement(agreement["id"], BCM_HEADERS))
    assert row["status"] == "SENT"
    assert row["countersigned_at"] is None
    assert read_reseller(reseller["id"])["authorization_status"] == "PENDING_AGREEMENT"


def test_supply_hold_release_during_suspension_rejected():
    """A suspension hold is a legal state, not a warehouse setting.

    PRD: "A hold whose reason is `SUSPENSION` or `TERMINATION` may **not** be released on
    this route — the attempt is rejected with `ERR_SUPPLY_BLOCKED_BY_AUTHORIZATION`,
    because lifting a suspension is a legal act on the authorization axis and not a
    warehouse decision."

    Design: Corner/state_machines/supply_hold_release_during_suspension_rejected
    """
    world = _ladder_to_suspension(_authorized_channel())
    suspended = read_reseller(world["reseller"]["id"])
    assert suspended["authorization_status"] == "SUSPENDED"
    assert suspended["supply_status"] == "HOLD"
    assert suspended["hold_reason"] == "SUSPENSION"

    validate_error(
        api_client.set_supply_status(
            world["reseller"]["id"], supply_status_payload("OPEN"), BCM_HEADERS
        ),
        "ERR_SUPPLY_BLOCKED_BY_AUTHORIZATION",
    )

    unchanged = read_reseller(world["reseller"]["id"])
    assert unchanged["supply_status"] == "HOLD"
    assert unchanged["hold_reason"] == "SUSPENSION"
    assert unchanged["version"] == suspended["version"]


def test_violation_third_dispute_round_rejected():
    """Two rejected rounds exhaust the right to dispute.

    PRD: "Two rejected rounds exhaust the reseller's right to dispute."

    Design: Corner/state_machines/violation_third_dispute_round_rejected
    """
    world = _warned(_authorized_channel())
    reseller_headers = make_reseller_headers(world["reseller"]["id"])
    for _round in range(2):
        validate_success(
            api_client.dispute_violation(
                world["violation"]["id"], violation_dispute_payload(), reseller_headers
            )
        )
        validate_success(
            api_client.decide_violation_dispute(
                world["violation"]["id"],
                violation_dispute_decision_payload("REJECT"),
                BCM_HEADERS,
            )
        )
    exhausted = read_violation(world["violation"]["id"])
    assert exhausted["status"] == "NOTICED"
    assert exhausted["dispute_rounds"] == 2

    validate_error(
        api_client.dispute_violation(
            world["violation"]["id"], violation_dispute_payload(), reseller_headers
        ),
        "ERR_DISPUTE_ROUNDS_EXHAUSTED",
    )

    row = read_violation(world["violation"]["id"])
    assert row["status"] == "NOTICED"
    assert row["dispute_rounds"] == 2


def test_termination_notice_rescission_rejected():
    """Cutting off supply is a decision the brand must live with.

    PRD: "A notice whose `rung` is `TERMINATION` may not be rescinded at all — the attempt
    is rejected with `ERR_TERMINATION_NOT_RESCINDABLE`, because cutting off supply is a
    decision the brand must live with."

    Design: Corner/state_machines/termination_notice_rescission_rejected
    """
    world = _ladder_to_suspension(_authorized_channel())
    termination = _terminate(world)
    assert termination["rung"] == "TERMINATION"

    validate_error(
        api_client.rescind_notice(
            termination["id"], {"rescinded_reason": "Reconsidered."}, COUNSEL_HEADERS
        ),
        "ERR_TERMINATION_NOT_RESCINDABLE",
    )

    assert read_notice(termination["id"])["status"] == "ISSUED"
    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "TERMINATED"
    assert reseller["supply_status"] == "CUT_OFF"


def test_serial_ship_downstream_by_a_non_holding_distributor_rejected():
    """Only the distributor named on the shipping record may record the next hop.

    PRD: "When `X-User-Role` is `Distributor`, `X-User-ID` is the `id` of the acting
    `Distributor` row; a distributor may only record downstream shipments for serial units
    whose `shipped_distributor_id` equals `X-User-ID`, and may only dispute chargebacks
    whose `distributor_id` equals `X-User-ID`, and may only read rows it owns. A violation
    of either ownership rule is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/state_machines/serial_ship_downstream_by_a_non_holding_distributor_rejected
    """
    world = _authorized_channel()
    holder = create_distributor(legal_name="Northwind Distribution")
    stranger = create_distributor(legal_name="Southwind Distribution")
    unit = create_serial_unit(world["product"]["id"], holder["id"], lot_code="LOT-A")

    validate_error(
        api_client.ship_downstream(
            unit["id"],
            ship_downstream_payload(world["reseller"]["id"]),
            make_distributor_headers(stranger["id"]),
        ),
        "ERR_NOT_RESOURCE_OWNER",
    )

    row = read_serial_unit(unit["id"])
    assert row["status"] == "SHIPPED_TO_DISTRIBUTOR"
    assert row["downstream_reseller_id"] is None
    assert row["version"] == 1


def test_chargeback_dispute_by_a_different_distributor_rejected():
    """A distributor may only dispute the chargebacks billed to it.

    PRD: "When `X-User-Role` is `Distributor`, `X-User-ID` is the `id` of the acting
    `Distributor` row; a distributor may only record downstream shipments for serial units
    whose `shipped_distributor_id` equals `X-User-ID`, and may only dispute chargebacks
    whose `distributor_id` equals `X-User-ID`, and may only read rows it owns. A violation
    of either ownership rule is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/state_machines/chargeback_dispute_by_a_different_distributor_rejected
    """
    world = _assessed_chargeback()
    stranger = create_distributor(legal_name="Southwind Distribution")

    validate_error(
        api_client.dispute_chargeback(
            world["chargeback"]["id"],
            chargeback_dispute_payload(),
            make_distributor_headers(stranger["id"]),
        ),
        "ERR_NOT_RESOURCE_OWNER",
    )

    row = read_chargeback(world["chargeback"]["id"])
    assert row["status"] == "ASSESSED"
    assert row["dispute_reason"] is None
    assert row["version"] == 1


def test_cure_after_the_deadline_rejected():
    """The cure window closes on the deadline instant.

    PRD: "Cure requires the violation to be `NOTICED` and requires the current clock to be
    at or before `cure_deadline_at`, else `ERR_CURE_WINDOW_EXPIRED`."

    Design: Corner/state_machines/cure_after_the_deadline_rejected
    """
    world = _warned(_authorized_channel())
    assert_same_instant(
        read_violation(world["violation"]["id"])["cure_deadline_at"],
        "2026-08-30T00:00:00Z",
        "cure_deadline_at",
    )

    pin_clock(CLOCK_AUG_31)
    response = api_client.submit_cure(
        world["violation"]["id"],
        cure_submission_payload(),
        make_reseller_headers(world["reseller"]["id"]),
    )
    validate_error(response, "ERR_CURE_WINDOW_EXPIRED")
    assert response.status_code == 409

    row = read_violation(world["violation"]["id"])
    assert row["status"] == "NOTICED"
    assert row["resolution_reason"] is None
    assert read_notice(world["notice"]["id"])["status"] == "ISSUED"


# --------------------------------------------------------------------------- #
# Side effects an operation must execute
# --------------------------------------------------------------------------- #
def test_chargeback_creation_flags_sourcing_resellers_for_review():
    """Pushing a distributor onto probation reaches its sourcing resellers.

    PRD: "The distributor's `version` is advanced once for the whole assessment, and where
    the re-derivation moved the standing into `PROBATION` or `SUSPENDED`, every reseller
    whose `sourcing_distributor_id` names this distributor has its `review_required` flag
    recomputed and its `version` advanced where the value changed."

    Design: Corner/state_machines/chargeback_creation_flags_sourcing_resellers_for_review
    """
    world = _assessed_chargeback(reseller_overrides={"legal_name": "Acme Retail LLC"})

    chargeback = world["chargeback"]
    assert chargeback["tier_rate_cents_per_unit"] == tier_rate_for_score(0) == 2500
    assert chargeback["amount_cents"] == 2500 * 4 == 10000
    assert chargeback["score_delta_applied"] == score_delta(4) == 10.0

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["standing"] == "PROBATION"
    assert distributor["diversion_score"] == 10.0

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["sourcing_distributor_id"] == world["distributor"]["id"]
    assert reseller["review_required"] is True
    assert reseller["version"] == 2


def test_chargeback_reversal_clears_the_reseller_review_flag():
    """The reversal walks the same path backwards, flag included.

    PRD: "A `decision` of `REVERSE` moves it `DISPUTED → REVERSED`, its single terminal
    state: `decision_reason` is recorded, the chargeback's `version` is advanced,
    `amount_cents` is subtracted from the distributor's `chargeback_balance_cents`,
    `score_delta_applied` is subtracted from its `diversion_score`, `standing` is
    re-derived from the restored score with the distributor's `version` advanced, and —
    because a standing that falls back from `PROBATION` to `GOOD` changes who is under
    review — the `review_required` flag is recomputed for every reseller whose
    `sourcing_distributor_id` names this distributor, with each changed reseller's
    `version` advanced."

    Design: Corner/state_machines/chargeback_reversal_clears_the_reseller_review_flag
    """
    world = _assessed_chargeback(reseller_overrides={"legal_name": "Acme Retail LLC"})
    assert read_reseller(world["reseller"]["id"])["review_required"] is True

    validate_success(
        api_client.dispute_chargeback(
            world["chargeback"]["id"],
            chargeback_dispute_payload(),
            make_distributor_headers(world["distributor"]["id"]),
        )
    )
    validate_success(
        api_client.decide_chargeback_dispute(
            world["chargeback"]["id"],
            chargeback_dispute_decision_payload("REVERSE"),
            COUNSEL_HEADERS,
        )
    )

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 0
    assert distributor["diversion_score"] == 0
    assert distributor["standing"] == "GOOD"

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["review_required"] is False
    assert reseller["version"] == 3


def test_publication_side_effect_backlinks_the_superseded_policy():
    """Publishing a second revision writes the backlink onto the first.

    PRD: "It also performs the supersession cascade: if any *other* policy is currently in
    status `PUBLISHED` — and by construction there is at most one — that policy moves
    `PUBLISHED → SUPERSEDED`, has its `superseded_by_policy_id` set to the newly published
    policy's `id`, and has its own `version` advanced."

    Design: Corner/state_machines/publication_side_effect_backlinks_the_superseded_policy
    """
    pin_clock(CLOCK_AUG_01)
    first = create_published_policy(CLOCK_AUG_01)
    assert first["status"] == "PUBLISHED"
    assert first["superseded_by_policy_id"] is None

    approved = create_approved_policy()
    second = validate_success(
        api_client.publish_policy(
            approved["id"], policy_publish_payload(CLOCK_AUG_01), COUNSEL_HEADERS
        )
    )

    assert second["status"] == "PUBLISHED"
    assert second["superseded_by_policy_id"] is None

    displaced = read_policy(first["id"])
    assert displaced["status"] == "SUPERSEDED"
    assert displaced["superseded_by_policy_id"] == second["id"]
    assert displaced["version"] == first["version"] + 1


def test_exception_approval_counts_the_violations_it_voided():
    """Only the violations the new floor actually lifts are counted.

    PRD: "The number of violations the cascade voided is recorded on the exception as
    `voided_violation_count`, and the exception's own `version` is advanced."

    Design: Corner/state_machines/exception_approval_counts_the_violations_it_voided
    """
    world = _authorized_channel(
        permitted_channels=["MARKETPLACE", "OWN_WEBSITE", "RETAILER_SITE"]
    )
    pin_clock(CLOCK_AUG_20)
    lifted_one, _o1, _e1 = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=evidence_hash(0),
        listing_url="https://marketplace.example/acme/1",
        seller_display_name="Acme Store",
    )
    lifted_two, _o2, _e2 = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=13000,
        channel="RETAILER_SITE",
        observed_at=OBSERVED_AUG_19,
        evidence_hash=evidence_hash(1),
        listing_url="https://retailer.example/acme/2",
        seller_display_name="Acme Store",
    )
    still_below, _o3, _e3 = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=evidence_hash(2),
        listing_url="https://marketplace.example/acme/3",
        seller_display_name="Acme Store",
    )

    approved = approve_exception(
        _requested_exception(world["product"]["id"])["id"],
        decision_reason="Marketing plan cleared.",
    )

    assert approved["override_floor_cents"] == 13000
    assert approved["voided_violation_count"] == 2
    assert approved["version"] == 2

    for violation_id in (lifted_one["id"], lifted_two["id"]):
        row = read_violation(violation_id)
        assert row["status"] == "VOIDED"
        assert row["resolution_reason"] == "RETROACTIVE_EXCEPTION"
    assert read_violation(still_below["id"])["status"] == "DETECTED"

    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 0


def test_notice_issuance_writes_both_the_ledger_and_the_notice_snapshot():
    """One issuance writes the violation, the reseller ledger and the notice.

    PRD: "And the notice itself is created in status `ISSUED`, carrying the computed
    `rung`, the snapshotted `cumulative_points_at_issue`, an `assessed_points` mirroring
    the figure charged onto the violation, and `issued_by_user_id` stamped from the
    issuer's `X-User-ID`, with `acknowledged_at` and `closed_reason` null."

    Design: Corner/state_machines/notice_issuance_writes_both_the_ledger_and_the_notice_snapshot
    """
    world = _authorized_channel()
    reseller_version_before = current_reseller_version(world["reseller"]["id"])
    _warned(world)
    notice = world["notice"]

    assert notice["status"] == "ISSUED"
    assert notice["rung"] == "WARNING"
    assert notice["assessed_points"] == violation_points(15000, 14000, "MARKETPLACE", 0) == 3
    assert notice["cumulative_points_at_issue"] == 3
    assert notice["issued_by_user_id"] == "bcm-1"
    assert notice["acknowledged_at"] is None
    assert notice["closed_reason"] is None
    assert notice["version"] == 1

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "NOTICED"
    assert violation["assessed_points"] == 3
    assert violation["assessed_floor_cents"] == 15000

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 3
    assert reseller["version"] == reseller_version_before + 1


# --------------------------------------------------------------------------- #
# Operations that must be no-ops
# --------------------------------------------------------------------------- #
def test_repeated_sweep_at_the_same_clock_reports_all_zero_counters():
    """A second sweep at the same instant finds nothing left to do.

    PRD: "Running the sweep when nothing is due is legal and returns four zeroes."

    Design: Corner/state_machines/repeated_sweep_at_the_same_clock_reports_all_zero_counters
    """
    world = _warned(_authorized_channel())

    pin_clock(CLOCK_AUG_31)
    first = run_sweep()
    assert first["escalated_violations"] == 1
    assert first["expired_agreements"] == 0
    assert first["expired_exceptions"] == 0
    assert first["reinstated_resellers"] == 0
    assert_same_instant(first["swept_at"], CLOCK_AUG_31, "swept_at")
    escalated = read_violation(world["violation"]["id"])
    assert escalated["status"] == "ESCALATED"

    second = run_sweep()

    assert second["expired_agreements"] == 0
    assert second["expired_exceptions"] == 0
    assert second["escalated_violations"] == 0
    assert second["reinstated_resellers"] == 0
    assert_same_instant(second["swept_at"], CLOCK_AUG_31, "swept_at")

    unchanged = read_violation(world["violation"]["id"])
    assert unchanged["status"] == "ESCALATED"
    assert unchanged["version"] == escalated["version"]
    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 3


def test_second_traced_unit_leaves_review_required_and_version_unchanged():
    """The review predicate is recomputed idempotently, not accumulated.

    PRD: "This recomputation runs when a distributor's standing changes, when a serialized
    unit becomes traced, and when a reseller is created — and it is idempotent: if the
    recomputed value equals the stored value, the reseller row is not touched and its
    `version` does not advance."

    Design: Corner/state_machines/second_traced_unit_leaves_review_required_and_version_unchanged
    """
    world = _authorized_channel()
    distributor = create_distributor(legal_name="Northwind Distribution")
    first_unit = create_serial_unit(world["product"]["id"], distributor["id"], lot_code="LOT-A")
    second_unit = create_serial_unit(world["product"]["id"], distributor["id"], lot_code="LOT-A")
    ship_unit_downstream(first_unit["id"], distributor["id"], world["reseller"]["id"])
    ship_unit_downstream(second_unit["id"], distributor["id"], world["reseller"]["id"])
    version_before = read_reseller(world["reseller"]["id"])["version"]

    pin_clock(CLOCK_AUG_20)
    first_observation = _grey_listing(world["product"]["id"], index=3, suffix="1")
    first_purchase = order_test_purchase(first_observation["id"], ordered_at=OBSERVED_AUG_19)
    capture_purchase_serial(first_purchase["id"], first_unit["serial_number"])
    validate_success(
        api_client.confirm_outcome(
            first_purchase["id"], confirm_outcome_payload("UNAUTHORIZED"), ANALYST_HEADERS
        )
    )
    after_first = read_reseller(world["reseller"]["id"])
    assert after_first["review_required"] is True
    assert after_first["version"] == version_before + 1

    second_observation = _grey_listing(world["product"]["id"], index=4, suffix="2")
    second_purchase = order_test_purchase(second_observation["id"], ordered_at=OBSERVED_AUG_19)
    capture_purchase_serial(second_purchase["id"], second_unit["serial_number"])
    validate_success(
        api_client.confirm_outcome(
            second_purchase["id"], confirm_outcome_payload("UNAUTHORIZED"), ANALYST_HEADERS
        )
    )

    assert read_serial_unit(second_unit["id"])["status"] == "TRACED_UNAUTHORIZED"
    after_second = read_reseller(world["reseller"]["id"])
    assert after_second["review_required"] is True
    assert after_second["version"] == after_first["version"]
