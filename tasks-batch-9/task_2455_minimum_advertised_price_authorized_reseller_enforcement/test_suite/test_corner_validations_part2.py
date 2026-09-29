"""Rejection-order corners, part two: transition legality, optimistic concurrency,
the antitrust guardrails and the cross-entity referential preconditions.

The ordering pairs deliberately break two rules at once so that the higher
priority code is the one the client observes.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST_HEADERS,
    BCM_HEADERS,
    COUNSEL_2_HEADERS,
    COUNSEL_HEADERS,
    ApiErrorId,
    api_client,
    make_reseller_headers,
)
from test_helpers.constants import EVIDENCE_HASH_1, EVIDENCE_HASH_3
from test_helpers.factories import (
    agreement_payload,
    agreement_response_payload,
    chargeback_payload,
    clearance_exception_payload,
    exception_decision_payload,
    exception_payload,
    notice_payload,
    product_payload,
    rescind_payload,
    supply_status_payload,
)
from test_helpers.fixtures import (
    capture_observation,
    capture_purchase_serial,
    confirm_unauthorized,
    create_active_agreement,
    create_detected_violation,
    create_distributor,
    create_draft_policy,
    create_policy_in_review,
    create_product,
    create_published_policy,
    create_reseller,
    create_sent_agreement,
    create_serial_unit,
    current_distributor_version,
    current_reseller_version,
    evaluate_observation,
    hold_supply,
    issue_notice,
    order_test_purchase,
    pin_clock,
    read_agreement,
    read_distributor,
    read_exception,
    read_notice,
    read_observation,
    read_policy,
    read_product,
    read_reseller,
    read_violation,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
OBSERVED_AUG_19 = "2026-08-19T00:00:00Z"
ORDERED_AUG_19 = "2026-08-19T00:00:00Z"
TERM_ENDS = "2027-06-30T00:00:00Z"
SUSPENSION_STARTS = "2026-09-01T00:00:00Z"
SUSPENSION_ENDS = "2026-09-10T00:00:00Z"
EXCEPTION_STARTS = "2026-08-10T00:00:00Z"
EXCEPTION_ENDS = "2026-08-25T00:00:00Z"

STANDARD_FLOOR = 15000


# --------------------------------------------------------------------------- #
# Shared spine
# --------------------------------------------------------------------------- #
def _published_policy():
    pin_clock(CLOCK_AUG_01)
    return create_published_policy(effective_from=CLOCK_AUG_01)


def _headphones(policy_id):
    return create_product(
        policy_id,
        sku="SKU-AUDIO-1",
        name="Studio Headphones",
        msrp_cents=20000,
        standard_map_floor_cents=STANDARD_FLOOR,
    )


def _acme():
    return create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )


def _authorize(reseller_id, policy_id):
    return create_active_agreement(
        reseller_id,
        policy_id,
        permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
        quality_obligations=["AUTHENTICITY_LABELING"],
        term_ends_at=TERM_ENDS,
    )


def _authorized_channel():
    """Published policy, headphones and an authorized Acme on the marketplace."""
    policy = _published_policy()
    product = _headphones(policy["id"])
    reseller = _acme()
    agreement = _authorize(reseller["id"], policy["id"])
    return {
        "policy": policy,
        "product": product,
        "reseller": reseller,
        "agreement": agreement,
    }


def _detected_first_breach(world):
    """A 14000 marketplace listing detected against Acme: three points."""
    pin_clock(CLOCK_AUG_20)
    violation, observation, _evaluation = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_18,
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/1",
        evidence_hash=EVIDENCE_HASH_1,
    )
    world["violation"] = violation
    world["observation"] = observation
    return world


def _warned_acme():
    world = _detected_first_breach(_authorized_channel())
    world["notice"] = issue_notice(world["reseller"]["id"], world["violation"]["id"])
    return world


def _suspended_acme():
    """Acme warned once and then suspended on an eleven-point second breach."""
    world = _warned_acme()
    violation2, _observation2, _evaluation2 = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=9000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_18,
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/2",
        evidence_hash=EVIDENCE_HASH_3,
    )
    world["violation2"] = violation2
    world["notice2"] = issue_notice(
        world["reseller"]["id"],
        violation2["id"],
        suspension_starts_at=SUSPENSION_STARTS,
        suspension_ends_at=SUSPENSION_ENDS,
    )
    return world


def _suspended_acme_with_third_breach():
    """Two rungs served and a third breach sitting in DETECTED."""
    world = _suspended_acme()
    violation3, _observation3, _evaluation3 = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_19,
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/3",
        evidence_hash=EVIDENCE_HASH_1,
    )
    world["violation3"] = violation3
    return world


def _terminate(world, headers=COUNSEL_HEADERS):
    return issue_notice(
        world["reseller"]["id"],
        world["violation3"]["id"],
        headers=headers,
        delivery_channel="CERTIFIED_MAIL",
        rung="TERMINATION",
    )


def _northwind():
    return create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )


def _grey_listing(product_id, listing_url, listed_price_cents, evidence_hash):
    observation = capture_observation(
        product_id,
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url=listing_url,
        listed_price_cents=listed_price_cents,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=evidence_hash,
    )
    evaluate_observation(observation["id"])
    return observation


def _confirmed_trace(product_id, distributor_id, serial_number, listing_url, evidence_hash):
    """Register a unit, buy the grey listing, read the serial and confirm the finding."""
    unit = create_serial_unit(
        product_id, distributor_id, serial_number=serial_number, lot_code="LOT-A"
    )
    observation = _grey_listing(product_id, listing_url, 9000, evidence_hash)
    purchase = order_test_purchase(
        observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9000
    )
    capture_purchase_serial(purchase["id"], serial_number)
    purchase = confirm_unauthorized(
        purchase["id"], outcome_reason="Seller has no agreement on file"
    )
    return purchase, unit, observation


# --------------------------------------------------------------------------- #
# Priority 7 — transition legality
# --------------------------------------------------------------------------- #
def test_submitting_a_policy_for_review_twice_is_an_invalid_state():
    """A policy already in legal review has no second submit transition.

    PRD: "The target row is in a state from which the requested transition is declared,
    else one of `ERR_INVALID_STATE`, `ERR_ALREADY_EVALUATED`,
    `ERR_VIOLATION_NOT_NOTICEABLE`, `ERR_RESELLER_TERMINATED`,
    `ERR_TERMINATION_NOT_RESCINDABLE` or `ERR_SUPPLY_BLOCKED_BY_AUTHORIZATION`, all HTTP
    409."

    Design: Corner/validations/submit_review_twice_returns_invalid_state
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_policy_in_review(policy_code="MAP-2026-A")

    validate_error(
        api_client.submit_policy_review(policy["id"], BCM_HEADERS),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    unchanged = read_policy(policy["id"])
    assert unchanged["status"] == "IN_LEGAL_REVIEW"
    assert unchanged["revision_number"] == 1


def test_evaluating_the_same_observation_twice_is_already_evaluated():
    """The specialised code fires once evaluation_status has left CAPTURED.

    PRD: "It requires `evaluation_status` to be `CAPTURED` — a second attempt on an
    already-evaluated row is rejected with `ERR_ALREADY_EVALUATED` — and it requires a
    governing policy to exist for `observed_at` in the sense of §3.1, with the selected
    policy being one whose status is `PUBLISHED`, `SUPERSEDED` or `WITHDRAWN` and whose
    `effective_from` is at or before `observed_at`; otherwise `ERR_NO_GOVERNING_POLICY`."

    Design: Corner/validations/evaluating_an_observation_twice_rejected
    """
    world = _detected_first_breach(_authorized_channel())

    validate_error(
        api_client.evaluate_observation(world["observation"]["id"], ANALYST_HEADERS),
        ApiErrorId.ERR_ALREADY_EVALUATED.value,
    )

    observation = read_observation(world["observation"]["id"])
    assert observation["evaluation_status"] == "EVALUATED_BREACH"

    rows, meta = validate_paginated(
        api_client.list_violations(
            BCM_HEADERS, params={"reseller_id": world["reseller"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == world["violation"]["id"]


def test_a_second_notice_for_an_already_noticed_violation_is_refused():
    """Issuance demands a DETECTED violation, so the ledger cannot be charged twice.

    PRD: "The violation must be in status `DETECTED`, else
    `ERR_VIOLATION_NOT_NOTICEABLE`."

    Design: Corner/validations/issuing_a_second_notice_for_a_noticed_violation_rejected
    """
    world = _warned_acme()
    validate_error(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                world["violation"]["id"],
                current_reseller_version(world["reseller"]["id"]),
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_VIOLATION_NOT_NOTICEABLE.value,
    )

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "NOTICED"
    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 3


def test_no_further_notice_may_be_issued_against_a_terminated_reseller():
    """The terminal authorization state closes enforcement for good.

    PRD: "The reseller's `authorization_status` must not be `TERMINATED`, else
    `ERR_RESELLER_TERMINATED`."

    Design: Corner/validations/issuing_a_notice_against_a_terminated_reseller_rejected
    """
    world = _suspended_acme_with_third_breach()
    # Captured while the agreement still governs the channel, evaluated afterwards so
    # the violation is born in DETECTED rather than being closed moot by termination.
    late_observation = capture_observation(
        world["product"]["id"],
        channel="OWN_WEBSITE",
        seller_display_name="Acme Store",
        listing_url="https://acme.example/l/4",
        listed_price_cents=12000,
        observed_at=OBSERVED_AUG_19,
        evidence_hash=EVIDENCE_HASH_3,
        matched_reseller_id=world["reseller"]["id"],
    )
    _terminate(world)
    evaluation = evaluate_observation(late_observation["id"])
    late_violation_id = evaluation["violation_id"]
    assert read_violation(late_violation_id)["status"] == "DETECTED"

    validate_error(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                late_violation_id,
                current_reseller_version(world["reseller"]["id"]),
            ),
            COUNSEL_2_HEADERS,
        ),
        ApiErrorId.ERR_RESELLER_TERMINATED.value,
    )

    assert read_reseller(world["reseller"]["id"])["authorization_status"] == "TERMINATED"
    _rows, meta = validate_paginated(
        api_client.list_notices(BCM_HEADERS, params={"reseller_id": world["reseller"]["id"]})
    )
    assert meta["total_count"] == 3


def test_a_termination_notice_may_not_be_rescinded():
    """Cutting off supply is the one act counsel cannot unwind.

    PRD: "A notice whose `rung` is `TERMINATION` may not be rescinded at all — the
    attempt is rejected with `ERR_TERMINATION_NOT_RESCINDABLE`, because cutting off
    supply is a decision the brand must live with."

    Design: Corner/validations/rescinding_a_termination_notice_rejected
    """
    world = _suspended_acme_with_third_breach()
    termination = _terminate(world)
    assert termination["rung"] == "TERMINATION"

    validate_error(
        api_client.rescind_notice(
            termination["id"],
            rescind_payload(rescinded_reason="Reconsidered after counsel review"),
            COUNSEL_2_HEADERS,
        ),
        ApiErrorId.ERR_TERMINATION_NOT_RESCINDABLE.value,
    )

    assert read_notice(termination["id"])["status"] == "ISSUED"
    assert read_reseller(world["reseller"]["id"])["authorization_status"] == "TERMINATED"


def test_supply_may_not_be_reopened_while_the_hold_reason_is_suspension():
    """The warehouse route cannot unlock a hold the ladder installed.

    PRD: "A hold whose reason is `SUSPENSION` or `TERMINATION` may **not** be released on
    this route — the attempt is rejected with `ERR_SUPPLY_BLOCKED_BY_AUTHORIZATION`,
    because lifting a suspension is a legal act on the authorization axis and not a
    warehouse decision."

    Design: Corner/validations/reopening_supply_for_a_suspended_reseller_rejected
    """
    world = _suspended_acme()
    validate_error(
        api_client.set_supply_status(
            world["reseller"]["id"],
            supply_status_payload("OPEN", note="Buyer requests restock"),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_SUPPLY_BLOCKED_BY_AUTHORIZATION.value,
    )

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "SUSPENSION"


# --------------------------------------------------------------------------- #
# Priority 8 — optimistic concurrency
# --------------------------------------------------------------------------- #
def test_a_notice_replaying_a_superseded_reseller_version_is_refused():
    """An intervening supply-status move invalidates the version the client read.

    PRD: "If that value does not equal the reseller's current `version`, the request is
    rejected with `ERR_STALE_RESELLER_VERSION` (HTTP 412)."

    Design: Corner/validations/notice_with_stale_reseller_version_rejected
    """
    world = _detected_first_breach(_authorized_channel())
    stale_version = current_reseller_version(world["reseller"]["id"])
    hold_supply(world["reseller"]["id"], hold_reason="QUALITY_OBLIGATION")

    validate_error(
        api_client.issue_notice(
            notice_payload(world["reseller"]["id"], world["violation"]["id"], stale_version),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_STALE_RESELLER_VERSION.value,
    )

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "DETECTED"
    assert violation["assessed_points"] is None
    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 0


def test_a_second_chargeback_replaying_the_first_ones_version_is_refused():
    """The distributor version the client read was consumed by the first assessment.

    PRD: "If that value does not equal the distributor's current `version`, the request
    is rejected with `ERR_STALE_DISTRIBUTOR_VERSION` (HTTP 412)."

    Design: Corner/validations/chargeback_with_stale_distributor_version_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    distributor = _northwind()
    pin_clock(CLOCK_AUG_20)
    first_purchase, _unit1, _obs1 = _confirmed_trace(
        product["id"], distributor["id"], "SN-0001", "https://mkt.example/l/9", EVIDENCE_HASH_1
    )
    second_purchase, _unit2, _obs2 = _confirmed_trace(
        product["id"], distributor["id"], "SN-0003", "https://mkt.example/l/10", EVIDENCE_HASH_3
    )

    captured_version = current_distributor_version(distributor["id"])
    validate_success(
        api_client.assess_chargeback(
            chargeback_payload(
                distributor["id"], first_purchase["id"], captured_version, diverted_units=4
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    validate_error(
        api_client.assess_chargeback(
            chargeback_payload(
                distributor["id"], second_purchase["id"], captured_version, diverted_units=2
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_STALE_DISTRIBUTOR_VERSION.value,
    )

    ledger = read_distributor(distributor["id"])
    assert ledger["chargeback_balance_cents"] == 10000
    assert ledger["diversion_score"] == 10.0

    _rows, meta = validate_paginated(
        api_client.list_chargebacks(BCM_HEADERS, params={"distributor_id": distributor["id"]})
    )
    assert meta["total_count"] == 1


def test_an_illegal_transition_outranks_a_stale_reseller_version():
    """Transition legality is settled before the concurrency token is compared.

    PRD: "When a single request violates several rules, exactly one error is returned,
    and which one is fully determined."

    Design: Corner/validations/state_check_precedes_occ_check_rejected
    """
    world = _authorized_channel()
    pin_clock(CLOCK_AUG_20)
    violation, _observation, _evaluation = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_18,
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/1",
    )
    stale_version = current_reseller_version(world["reseller"]["id"])
    issue_notice(world["reseller"]["id"], violation["id"])

    validate_error(
        api_client.issue_notice(
            notice_payload(world["reseller"]["id"], violation["id"], stale_version),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_VIOLATION_NOT_NOTICEABLE.value,
    )

    _rows, meta = validate_paginated(
        api_client.list_notices(BCM_HEADERS, params={"reseller_id": world["reseller"]["id"]})
    )
    assert meta["total_count"] == 1


def test_a_stale_reseller_version_outranks_the_antitrust_guardrail():
    """The concurrency gate is the one check that precedes the antitrust guardrails.

    PRD: "Note the consequence of this position: an antitrust failure is reported even
    when the request would also have failed a referential, temporal or domain check, but
    a stale-version failure is reported ahead of an antitrust failure."

    Design: Corner/validations/occ_check_precedes_antitrust_check_rejected
    """
    world = _detected_first_breach(_authorized_channel())
    stale_version = current_reseller_version(world["reseller"]["id"])
    hold_supply(world["reseller"]["id"], hold_reason="QUALITY_OBLIGATION")

    validate_error(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                world["violation"]["id"],
                stale_version,
                contains_pricing_discussion=True,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_STALE_RESELLER_VERSION.value,
    )

    assert read_violation(world["violation"]["id"])["status"] == "DETECTED"


# --------------------------------------------------------------------------- #
# Priority 9 — antitrust guardrails
# --------------------------------------------------------------------------- #
def test_an_agreement_declaring_price_terms_is_refused_on_antitrust_grounds():
    """No draft agreement is ever persisted carrying a resale price term.

    PRD: "An authorized reseller agreement may not declare that it contains price terms:
    if a draft carries `price_terms_included` set to true, it is rejected with
    `ERR_ANTITRUST_PRICE_TERM_IN_AGREEMENT` (HTTP 422)."

    Design: Corner/validations/agreement_carrying_price_terms_rejected
    """
    policy = _published_policy()
    reseller = _acme()

    validate_error(
        api_client.create_agreement(
            agreement_payload(
                reseller["id"],
                policy["id"],
                permitted_channels=["MARKETPLACE"],
                quality_obligations=["AUTHENTICITY_LABELING"],
                term_ends_at=TERM_ENDS,
                price_terms_included=True,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_ANTITRUST_PRICE_TERM_IN_AGREEMENT.value,
    )

    _rows, meta = validate_paginated(api_client.list_agreements(BCM_HEADERS))
    assert meta["total_count"] == 0
    assert read_reseller(reseller["id"])["authorization_status"] == "APPLIED"


def test_a_countersignature_carrying_a_counter_price_is_refused():
    """Entertaining a counter-proposal is the negotiation the posture forbids.

    PRD: "A reseller's response to an agreement may not carry a price counter-proposal:
    if the response supplies `counter_price_proposal_cents` at all, it is rejected with
    `ERR_ANTITRUST_NEGOTIATION_PROHIBITED` (HTTP 422), because entertaining a
    counter-proposal is exactly the negotiation the unilateral posture forbids."

    Design: Corner/validations/countersignature_with_a_counter_price_rejected
    """
    policy = _published_policy()
    reseller = _acme()
    agreement = create_sent_agreement(
        reseller["id"],
        policy["id"],
        permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
        term_ends_at=TERM_ENDS,
    )

    validate_error(
        api_client.respond_agreement(
            agreement["id"],
            agreement_response_payload("COUNTERSIGN", counter_price_proposal_cents=14000),
            make_reseller_headers(reseller["id"]),
        ),
        ApiErrorId.ERR_ANTITRUST_NEGOTIATION_PROHIBITED.value,
    )

    assert read_agreement(agreement["id"])["status"] == "SENT"
    assert read_reseller(reseller["id"])["authorization_status"] == "PENDING_AGREEMENT"


def test_an_exception_sourced_from_a_reseller_price_request_is_refused():
    """Reseller-originated price input never enters the exception record.

    PRD: "And a pricing exception may not be sourced from a dealer's price request: if
    `dealer_input_source` is `RESELLER_PRICING_REQUEST`, the request is rejected with
    `ERR_ANTITRUST_DEALER_PRICE_INPUT` (HTTP 422)."

    Design: Corner/validations/exception_sourced_from_a_reseller_price_request_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])

    validate_error(
        api_client.create_exception(
            exception_payload(
                product["id"],
                exception_type="PROMOTIONAL_EVENT",
                starts_at=EXCEPTION_STARTS,
                ends_at=EXCEPTION_ENDS,
                channel_scope="ALL",
                requested_override_floor_cents=13000,
                dealer_input_source="RESELLER_PRICING_REQUEST",
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_ANTITRUST_DEALER_PRICE_INPUT.value,
    )

    _rows, meta = validate_paginated(api_client.list_exceptions(BCM_HEADERS))
    assert meta["total_count"] == 0
    assert read_product(product["id"])["open_exception_count"] == 0


def test_the_antitrust_guardrail_outranks_the_missing_acknowledgement():
    """A counter price is reported even though the same reply also fails downstream.

    PRD: "Note the consequence of this position: an antitrust failure is reported even
    when the request would also have failed a referential, temporal or domain check, but
    a stale-version failure is reported ahead of an antitrust failure."

    Design: Corner/validations/antitrust_check_precedes_referential_check_rejected
    """
    policy = _published_policy()
    assert policy["non_negotiation_ack_required"] is True
    reseller = _acme()
    agreement = create_sent_agreement(
        reseller["id"],
        policy["id"],
        permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
        term_ends_at=TERM_ENDS,
    )

    validate_error(
        api_client.respond_agreement(
            agreement["id"],
            {"decision": "COUNTERSIGN", "counter_price_proposal_cents": 14000},
            make_reseller_headers(reseller["id"]),
        ),
        ApiErrorId.ERR_ANTITRUST_NEGOTIATION_PROHIBITED.value,
    )

    assert read_agreement(agreement["id"])["status"] == "SENT"


# --------------------------------------------------------------------------- #
# Priority 10 — cross-entity referential preconditions
# --------------------------------------------------------------------------- #
def test_a_product_may_not_be_registered_under_a_draft_policy():
    """The governing policy has to be published at the moment of registration.

    PRD: "Registration also names a `governing_policy_id`, and that policy must be in
    status `PUBLISHED` at the moment of registration, else `ERR_POLICY_NOT_PUBLISHED`."

    Design: Corner/validations/product_under_a_draft_policy_rejected
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_draft_policy(policy_code="MAP-2026-A")

    validate_error(
        api_client.create_product(
            product_payload(
                policy["id"],
                sku="SKU-AUDIO-1",
                name="Studio Headphones",
                msrp_cents=20000,
                standard_map_floor_cents=STANDARD_FLOOR,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_POLICY_NOT_PUBLISHED.value,
    )

    assert read_policy(policy["id"])["status"] == "DRAFT"
    _rows, meta = validate_paginated(api_client.list_products(BCM_HEADERS))
    assert meta["total_count"] == 0


def test_a_notice_naming_a_reseller_other_than_the_violations_own_is_refused():
    """The notice subject must be the reseller the violation was opened against.

    PRD: "Separately, the payload's `reseller_id` must equal the violation's own
    `reseller_id`, else `ERR_VIOLATION_RESELLER_MISMATCH`."

    Design: Corner/validations/notice_naming_the_wrong_reseller_rejected
    """
    world = _authorized_channel()
    bravo = create_reseller(
        legal_name="Bravo Outlets Inc",
        contact_email="ops@bravo.example",
        primary_channel="RETAILER_SITE",
    )
    create_active_agreement(
        bravo["id"],
        world["policy"]["id"],
        permitted_channels=["RETAILER_SITE"],
        quality_obligations=["AUTHENTICITY_LABELING"],
        term_ends_at=TERM_ENDS,
    )
    world = _detected_first_breach(world)

    validate_error(
        api_client.issue_notice(
            notice_payload(
                bravo["id"], world["violation"]["id"], current_reseller_version(bravo["id"])
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_VIOLATION_RESELLER_MISMATCH.value,
    )

    assert read_violation(world["violation"]["id"])["status"] == "DETECTED"
    assert read_reseller(bravo["id"])["violation_points_total"] == 0


def test_a_clearance_exception_on_an_active_product_may_not_be_approved():
    """The clearance floor is only installable once the product is in clearance.

    PRD: "Approval first requires the referenced product not to be in
    `lifecycle_status` `DISCONTINUED`, and additionally — when the `exception_type` is
    `CLEARANCE` — requires the product to be in `lifecycle_status` `CLEARANCE`, else
    `ERR_PRODUCT_NOT_IN_CLEARANCE`."

    Design: Corner/validations/clearance_exception_on_an_active_product_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    assert product["lifecycle_status"] == "ACTIVE"
    pin_clock(CLOCK_AUG_20)
    exception = validate_success(
        api_client.create_exception(
            clearance_exception_payload(
                product["id"],
                starts_at=EXCEPTION_STARTS,
                ends_at=EXCEPTION_ENDS,
                channel_scope="ALL",
                dealer_input_source="BRAND_MARKETING_PLAN",
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    validate_error(
        api_client.decide_exception(
            exception["id"],
            exception_decision_payload(
                "APPROVE", decision_reason="Clearance depth cleared by legal"
            ),
            COUNSEL_HEADERS,
        ),
        ApiErrorId.ERR_PRODUCT_NOT_IN_CLEARANCE.value,
    )

    assert read_exception(exception["id"])["status"] == "REQUESTED"
    refreshed = read_product(product["id"])
    assert refreshed["lifecycle_status"] == "ACTIVE"
    assert refreshed["open_exception_count"] == 0
