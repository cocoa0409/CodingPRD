"""Declared transitions of the policy document, the agreement and the reseller.

The reseller carries two independent state axes on one row, so every transition
here is checked on both axes at once: the contractual `authorization_status` and
the physical `supply_status` with its `hold_reason`, together with the version
counters each transition advances.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import BCM_HEADERS, COUNSEL_HEADERS, api_client
from test_helpers.assertions import assert_same_instant
from test_helpers.constants import evidence_hash
from test_helpers.factories import (
    agreement_payload,
    agreement_response_payload,
    policy_publish_payload,
    policy_review_decision_payload,
    policy_withdraw_payload,
)
from test_helpers.fixtures import (
    create_active_agreement,
    create_detected_violation,
    create_distributor,
    create_draft_policy,
    create_policy_in_review,
    create_product,
    create_published_policy,
    create_reseller,
    create_serial_unit,
    hold_supply,
    issue_notice,
    pin_clock,
    read_agreement,
    read_notice,
    read_policy,
    read_product,
    read_reseller,
    read_serial_unit,
    read_violation,
    release_supply,
    rescind_notice,
    run_sweep,
    ship_unit_downstream,
)
from test_helpers.test_users import make_reseller_headers

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_15 = "2026-08-15T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
CLOCK_SEP_11 = "2026-09-11T00:00:00Z"
CLOCK_JUL_01_2027 = "2027-07-01T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
OBSERVED_AUG_19 = "2026-08-19T00:00:00Z"
TERM_ENDS_JUN_30_2027 = "2027-06-30T00:00:00Z"
SUSPENSION_STARTS = "2026-09-01T00:00:00Z"
SUSPENSION_ENDS = "2026-09-10T00:00:00Z"
DEFAULT_CHANNELS = ["MARKETPLACE", "OWN_WEBSITE"]


# --------------------------------------------------------------------------- #
# Shared setup
# --------------------------------------------------------------------------- #
def _policy_product_reseller():
    """A published policy, one product at a 15000 floor and a fresh applicant."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    product = create_product(policy["id"], name="Studio Headphones")
    reseller = create_reseller(legal_name="Acme Retail LLC", contact_email="ops@acme.example")
    return {"policy": policy, "product": product, "reseller": reseller}


def _drafted_agreement(permitted_channels=None):
    """The same trio with a DRAFT agreement waiting to be sent."""
    world = _policy_product_reseller()
    payload = agreement_payload(
        world["reseller"]["id"],
        world["policy"]["id"],
        permitted_channels=list(permitted_channels or DEFAULT_CHANNELS),
        quality_obligations=["AUTHENTICITY_LABELING"],
        term_ends_at=TERM_ENDS_JUN_30_2027,
    )
    world["agreement"] = validate_success(api_client.create_agreement(payload, BCM_HEADERS), 201)
    return world


def _authorized_channel(permitted_channels=None):
    """The trio carried all the way to AUTHORIZED on an ACTIVE agreement."""
    world = _policy_product_reseller()
    world["agreement"] = create_active_agreement(
        world["reseller"]["id"],
        world["policy"]["id"],
        permitted_channels=list(permitted_channels or DEFAULT_CHANNELS),
        quality_obligations=["AUTHENTICITY_LABELING"],
        term_ends_at=TERM_ENDS_JUN_30_2027,
    )
    return world


def _ladder_to_suspension(world):
    """A warning on a 14000 listing, then a suspension on a 9000 listing."""
    pin_clock(CLOCK_AUG_20)
    first, _obs, _ev = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=evidence_hash(0),
        listing_url="https://marketplace.example/acme/1",
        seller_display_name="Acme Store",
    )
    warning = issue_notice(world["reseller"]["id"], first["id"])
    second, _obs2, _ev2 = create_detected_violation(
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
    world["violations"] = [first, second]
    world["notices"] = [warning, suspension]
    return world


def _terminate(world, listed_price_cents=14000, observed_at=OBSERVED_AUG_19):
    """The third rung: counsel issues the termination the ladder now computes."""
    third, _obs, _ev = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=listed_price_cents,
        observed_at=observed_at,
        evidence_hash=evidence_hash(2),
        listing_url="https://marketplace.example/acme/3",
        seller_display_name="Acme Store",
    )
    notice = issue_notice(
        world["reseller"]["id"], third["id"], headers=COUNSEL_HEADERS, delivery_channel="CERTIFIED_MAIL"
    )
    world["violations"].append(third)
    world["notices"].append(notice)
    return notice


# --------------------------------------------------------------------------- #
# PricingPolicy
# --------------------------------------------------------------------------- #
def test_policy_draft_to_in_legal_review_on_submit_review():
    """Submission hands the draft to counsel and advances the document's version.

    PRD: "Submission for review is available to the `BrandChannelManager` and moves
    the document `DRAFT → IN_LEGAL_REVIEW`. It requires the policy to be in `DRAFT`,
    and it re-checks that `termination_points_threshold` is strictly greater than
    `suspension_points_threshold` — a draft whose ladder thresholds have been edited
    into an incoherent order cannot be handed to counsel. The transition advances the
    policy's `version`."

    Design: Corner/state_machines/policy_draft_to_in_legal_review_on_submit_review
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_draft_policy()
    assert policy["status"] == "DRAFT"

    submitted = validate_success(api_client.submit_policy_review(policy["id"], BCM_HEADERS))

    assert submitted["status"] == "IN_LEGAL_REVIEW"
    assert submitted["revision_number"] == 1
    assert submitted["version"] == 2


def test_policy_in_legal_review_to_draft_on_return_for_revision():
    """A return trip climbs revision_number and records the reviewing counsel.

    PRD: "A decision of `RETURN_FOR_REVISION` sends the document back,
    `IN_LEGAL_REVIEW → DRAFT`: it sets `revision_number` to one more than its previous
    value, records the supplied `legal_review_notes` and stamps `reviewed_by_user_id`
    with the reviewing counsel's `X-User-ID`, and advances `version`."

    Design: Corner/state_machines/policy_in_legal_review_to_draft_on_return_for_revision
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_policy_in_review()

    returned = validate_success(
        api_client.decide_policy_review(
            policy["id"],
            policy_review_decision_payload(
                "RETURN_FOR_REVISION", legal_review_notes="Tighten the channel language."
            ),
            COUNSEL_HEADERS,
        )
    )

    assert returned["status"] == "DRAFT"
    assert returned["revision_number"] == 2
    assert returned["legal_review_notes"] == "Tighten the channel language."
    assert returned["reviewed_by_user_id"] == "counsel-1"
    assert returned["version"] == 3


def test_policy_in_legal_review_to_approved_on_approve_for_publication():
    """Approval records the review but deliberately leaves revision_number alone.

    PRD: "A decision of `APPROVE_FOR_PUBLICATION` moves the document
    `IN_LEGAL_REVIEW → APPROVED`: it records `legal_review_notes` and
    `reviewed_by_user_id` and advances `version`, but does **not** touch
    `revision_number`."

    Design: Corner/state_machines/policy_in_legal_review_to_approved_on_approve_for_publication
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_policy_in_review()

    approved = validate_success(
        api_client.decide_policy_review(
            policy["id"],
            policy_review_decision_payload("APPROVE_FOR_PUBLICATION"),
            COUNSEL_HEADERS,
        )
    )

    assert approved["status"] == "APPROVED"
    assert approved["revision_number"] == 1
    assert approved["reviewed_by_user_id"] == "counsel-1"
    assert approved["effective_from"] is None
    assert approved["version"] == 3


def test_policy_approved_to_published_sets_effective_from_and_publisher():
    """Publication stores the scheduled instant and stamps the publishing counsel.

    PRD: "The transition stores `effective_from`, stamps `published_by_user_id` with
    the publishing counsel's `X-User-ID`, and advances the policy's `version`."

    Design: Corner/state_machines/policy_approved_to_published_sets_effective_from_and_publisher
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_policy_in_review()
    approved = validate_success(
        api_client.decide_policy_review(
            policy["id"], policy_review_decision_payload(), COUNSEL_HEADERS
        )
    )

    published = validate_success(
        api_client.publish_policy(
            approved["id"], policy_publish_payload(CLOCK_AUG_01), COUNSEL_HEADERS
        )
    )

    assert published["status"] == "PUBLISHED"
    assert_same_instant(published["effective_from"], CLOCK_AUG_01, "effective_from")
    assert published["published_by_user_id"] == "counsel-1"
    assert published["superseded_by_policy_id"] is None
    assert published["version"] == 4


def test_policy_published_to_withdrawn_does_not_cascade_to_products():
    """Withdrawal closes the gate on new enforcement and touches nothing else.

    PRD: "Withdrawal, again by `BrandLegalCounsel`, moves a policy
    `PUBLISHED → WITHDRAWN`, recording the supplied `withdrawn_reason` and advancing
    `version`. Withdrawal deliberately cascades to nothing: products keep their
    governing policy reference and open violations keep their citation."

    Design: Corner/state_machines/policy_published_to_withdrawn_does_not_cascade_to_products
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    product = create_product(policy["id"], name="Studio Headphones")

    withdrawn = validate_success(
        api_client.withdraw_policy(
            policy["id"],
            policy_withdraw_payload(withdrawn_reason="Programme paused for review."),
            COUNSEL_HEADERS,
        )
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawn_reason"] == "Programme paused for review."
    assert withdrawn["version"] == 5

    unchanged = read_product(product["id"])
    assert unchanged["governing_policy_id"] == policy["id"]
    assert unchanged["version"] == 1


def test_policy_published_to_superseded_when_a_second_policy_publishes():
    """A second publication displaces the incumbent and back-links to its successor.

    PRD: "It also performs the supersession cascade: if any *other* policy is
    currently in status `PUBLISHED` — and by construction there is at most one — that
    policy moves `PUBLISHED → SUPERSEDED`, has its `superseded_by_policy_id` set to the
    newly published policy's `id`, and has its own `version` advanced."

    Design: Corner/state_machines/policy_published_to_superseded_when_a_second_policy_publishes
    """
    pin_clock(CLOCK_AUG_01)
    incumbent = create_published_policy(CLOCK_AUG_01)

    successor = create_published_policy(CLOCK_AUG_15)

    displaced = read_policy(incumbent["id"])
    assert displaced["status"] == "SUPERSEDED"
    assert displaced["superseded_by_policy_id"] == successor["id"]
    assert displaced["version"] == 5

    assert successor["status"] == "PUBLISHED"
    assert successor["superseded_by_policy_id"] is None
    assert_same_instant(successor["effective_from"], CLOCK_AUG_15, "effective_from")

    rows, meta = validate_paginated(
        api_client.list_pricing_policies(BCM_HEADERS, params={"status": "PUBLISHED"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == successor["id"]


# --------------------------------------------------------------------------- #
# ResellerAgreement
# --------------------------------------------------------------------------- #
def test_agreement_draft_to_sent_pushes_reseller_to_pending_agreement():
    """Sending the paper is the only client act that moves the applicant forward.

    PRD: "The transition stamps `sent_at` with the current logical clock, advances the
    agreement's `version`, and moves the reseller's authorization axis
    `APPLIED → PENDING_AGREEMENT` while advancing the reseller's `version` as well. The
    reseller's supply axis is deliberately left on `HOLD` with reason
    `PENDING_AUTHORIZATION`."

    Design: Corner/state_machines/agreement_draft_to_sent_pushes_reseller_to_pending_agreement
    """
    world = _drafted_agreement()

    sent = validate_success(api_client.send_agreement(world["agreement"]["id"], BCM_HEADERS))

    assert sent["status"] == "SENT"
    assert_same_instant(sent["sent_at"], CLOCK_AUG_01, "sent_at")
    assert sent["version"] == 2

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "PENDING_AGREEMENT"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "PENDING_AUTHORIZATION"
    assert reseller["version"] == 2


def test_agreement_sent_to_countersigned_leaves_reseller_axes_untouched():
    """Countersignature is a one-row write; the reseller waits for activation.

    PRD: "Countersignature changes **no** reseller field: the authorization axis stays
    on `PENDING_AGREEMENT` and advances only at activation, so only the agreement's
    `version` moves."

    Design: Corner/state_machines/agreement_sent_to_countersigned_leaves_reseller_axes_untouched
    """
    world = _drafted_agreement()
    validate_success(api_client.send_agreement(world["agreement"]["id"], BCM_HEADERS))

    countersigned = validate_success(
        api_client.respond_agreement(
            world["agreement"]["id"],
            agreement_response_payload("COUNTERSIGN", non_negotiation_acknowledged=True),
            make_reseller_headers(world["reseller"]["id"]),
        )
    )

    assert countersigned["status"] == "COUNTERSIGNED"
    assert_same_instant(countersigned["countersigned_at"], CLOCK_AUG_01, "countersigned_at")
    assert countersigned["countersigned_by_user_id"] == world["reseller"]["id"]
    assert countersigned["non_negotiation_acknowledged"] is True
    assert countersigned["version"] == 3

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "PENDING_AGREEMENT"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "PENDING_AUTHORIZATION"
    assert reseller["version"] == 2


def test_agreement_sent_to_declined_rolls_reseller_back_to_applied():
    """The declining branch is the asymmetric one: it does reach the reseller.

    PRD: "Unlike countersignature, declining *does* touch the reseller: its
    `authorization_status` is rolled back to `APPLIED`, its `supply_status` set to
    `HOLD` and its `hold_reason` set to `PENDING_AUTHORIZATION`, with its `version`
    advanced."

    Design: Corner/state_machines/agreement_sent_to_declined_rolls_reseller_back_to_applied
    """
    world = _drafted_agreement()
    validate_success(api_client.send_agreement(world["agreement"]["id"], BCM_HEADERS))

    declined = validate_success(
        api_client.respond_agreement(
            world["agreement"]["id"],
            agreement_response_payload("DECLINE", decline_reason="Channel terms rejected."),
            make_reseller_headers(world["reseller"]["id"]),
        )
    )

    assert declined["status"] == "DECLINED"
    assert declined["closed_reason"] == "Channel terms rejected."
    assert declined["version"] == 3

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "APPLIED"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "PENDING_AUTHORIZATION"
    assert reseller["version"] == 3


def test_agreement_countersigned_to_active_opens_both_reseller_axes():
    """Activation is the single act that moves both reseller axes together.

    PRD: "Activation stamps `activated_at` with the current clock and advances the
    agreement's `version`, and it moves the reseller on both axes at once:
    `authorization_status` to `AUTHORIZED`, `supply_status` to `OPEN`, `hold_reason` to
    `NONE`, with the reseller's `version` advanced."

    Design: Corner/state_machines/agreement_countersigned_to_active_opens_both_reseller_axes
    """
    world = _drafted_agreement()
    validate_success(api_client.send_agreement(world["agreement"]["id"], BCM_HEADERS))
    validate_success(
        api_client.respond_agreement(
            world["agreement"]["id"],
            agreement_response_payload("COUNTERSIGN", non_negotiation_acknowledged=True),
            make_reseller_headers(world["reseller"]["id"]),
        )
    )

    active = validate_success(api_client.activate_agreement(world["agreement"]["id"], BCM_HEADERS))

    assert active["status"] == "ACTIVE"
    assert_same_instant(active["activated_at"], CLOCK_AUG_01, "activated_at")
    assert active["version"] == 4

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "AUTHORIZED"
    assert reseller["supply_status"] == "OPEN"
    assert reseller["hold_reason"] == "NONE"
    assert reseller["version"] == 3


def test_agreement_active_to_expired_holds_supply_axis_only():
    """A lapsed term stops the goods without touching the contractual axis.

    PRD: "When the sweep observes that `term_ends_at` is at or before the current
    clock, the agreement moves `ACTIVE → EXPIRED` with `closed_reason` recorded as
    `TERM_EXPIRED` and its `version` advanced, and the reseller's supply axis is pushed
    to `HOLD` with `hold_reason` `AGREEMENT_EXPIRED` while its `authorization_status` is
    left exactly as it was — the clearest demonstration of axis independence in the
    system, since a reseller with a lapsed agreement remains `AUTHORIZED` on paper but
    receives no goods."

    Design: Corner/state_machines/agreement_active_to_expired_holds_supply_axis_only
    """
    world = _authorized_channel()

    pin_clock(CLOCK_JUL_01_2027)
    counters = run_sweep()

    assert counters["expired_agreements"] == 1

    agreement = read_agreement(world["agreement"]["id"])
    assert agreement["status"] == "EXPIRED"
    assert agreement["closed_reason"] == "TERM_EXPIRED"
    assert agreement["version"] == 5

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "AUTHORIZED"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "AGREEMENT_EXPIRED"
    assert reseller["version"] == 4


def test_agreement_active_to_terminated_recalls_shipped_serial_units():
    """Termination of the paper is what recalls the stock already in the warehouse.

    PRD: "When the reseller's `authorization_status` becomes `TERMINATED`, the
    agreement moves `ACTIVE → TERMINATED` with `closed_reason` recorded as
    `SUPPLY_TERMINATED` and its `version` advanced, and this transition in turn recalls
    stock: every serialized unit whose `downstream_reseller_id` is this agreement's
    reseller and whose custody state is `SHIPPED_TO_RESELLER` moves to `RECALLED`, each
    with its own `version` advanced."

    Design: Corner/state_machines/agreement_active_to_terminated_recalls_shipped_serial_units
    """
    world = _authorized_channel()
    distributor = create_distributor(legal_name="Northwind Distribution")
    unit = create_serial_unit(world["product"]["id"], distributor["id"], lot_code="LOT-A")
    unit = ship_unit_downstream(unit["id"], distributor["id"], world["reseller"]["id"])
    assert unit["status"] == "SHIPPED_TO_RESELLER"

    _ladder_to_suspension(world)
    termination = _terminate(world)
    assert termination["rung"] == "TERMINATION"

    agreement = read_agreement(world["agreement"]["id"])
    assert agreement["status"] == "TERMINATED"
    assert agreement["closed_reason"] == "SUPPLY_TERMINATED"
    assert agreement["version"] == 5

    recalled = read_serial_unit(unit["id"])
    assert recalled["status"] == "RECALLED"
    assert recalled["downstream_reseller_id"] == world["reseller"]["id"]


# --------------------------------------------------------------------------- #
# Reseller — the two parallel axes
# --------------------------------------------------------------------------- #
def test_reseller_authorization_axis_applied_to_pending_agreement():
    """The contractual axis takes its first declared step and stops there.

    PRD: "`authorization_status` is the contractual axis, moving
    `APPLIED → PENDING_AGREEMENT → AUTHORIZED`, then optionally cycling
    `AUTHORIZED → SUSPENDED → AUTHORIZED`, and finally `AUTHORIZED` or
    `SUSPENDED → TERMINATED`."

    Design: Corner/state_machines/reseller_authorization_axis_applied_to_pending_agreement
    """
    world = _drafted_agreement()
    assert world["reseller"]["authorization_status"] == "APPLIED"

    validate_success(api_client.send_agreement(world["agreement"]["id"], BCM_HEADERS))

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "PENDING_AGREEMENT"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "PENDING_AUTHORIZATION"
    assert reseller["version"] == 2


def test_reseller_authorization_axis_pending_agreement_to_authorized():
    """Only activation clears the pending-authorization hold on the supply axis.

    PRD: "Likewise a `PENDING_AUTHORIZATION` hold is only cleared by activating an
    agreement."

    Design: Corner/state_machines/reseller_authorization_axis_pending_agreement_to_authorized
    """
    world = _drafted_agreement()
    validate_success(api_client.send_agreement(world["agreement"]["id"], BCM_HEADERS))
    validate_success(
        api_client.respond_agreement(
            world["agreement"]["id"],
            agreement_response_payload("COUNTERSIGN", non_negotiation_acknowledged=True),
            make_reseller_headers(world["reseller"]["id"]),
        )
    )
    pending = read_reseller(world["reseller"]["id"])
    assert pending["hold_reason"] == "PENDING_AUTHORIZATION"

    validate_success(api_client.activate_agreement(world["agreement"]["id"], BCM_HEADERS))

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "AUTHORIZED"
    assert reseller["supply_status"] == "OPEN"
    assert reseller["hold_reason"] == "NONE"
    assert reseller["version"] == 3


def test_reseller_authorization_axis_authorized_to_suspended_sets_window():
    """A suspension notice drags supply to HOLD and copies its own end instant over.

    PRD: "A `SUSPENSION` notice additionally drives the reseller's authorization axis
    to `SUSPENDED`, its supply axis to `HOLD` and its `hold_reason` to `SUSPENSION`, and
    copies the notice's `suspension_ends_at` onto the reseller's own
    `suspension_ends_at`; this is legal from either `AUTHORIZED` or `SUSPENDED`, but
    never from `TERMINATED`."

    Design: Corner/state_machines/reseller_authorization_axis_authorized_to_suspended_sets_window
    """
    world = _ladder_to_suspension(_authorized_channel())
    assert world["notices"][1]["rung"] == "SUSPENSION"

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "SUSPENDED"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "SUSPENSION"
    assert_same_instant(reseller["suspension_ends_at"], SUSPENSION_ENDS, "suspension_ends_at")
    assert reseller["terminated_at"] is None


def test_reseller_suspended_to_authorized_by_sweep_satisfies_the_notice():
    """Serving the window reinstates the reseller but keeps every point charged.

    PRD: "When the sweep observes a reseller whose `authorization_status` is
    `SUSPENDED`, whose `hold_reason` is `SUSPENSION` and whose `suspension_ends_at` is at
    or before the clock, the reseller returns to `AUTHORIZED` with `supply_status` `OPEN`
    and `hold_reason` `NONE`; `last_suspension_ended_at` is set to the
    `suspension_ends_at` that just elapsed (not to the sweep instant),
    `suspension_ends_at` is cleared to null, and the reseller's `version` is advanced.
    The governing suspension notice moves to `SATISFIED` with `closed_reason` recorded as
    `SUSPENSION_SERVED` and its own `version` advanced."

    Design: Corner/state_machines/reseller_suspended_to_authorized_by_sweep_satisfies_the_notice
    """
    world = _ladder_to_suspension(_authorized_channel())

    pin_clock(CLOCK_SEP_11)
    counters = run_sweep()

    assert counters["reinstated_resellers"] == 1

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "AUTHORIZED"
    assert reseller["supply_status"] == "OPEN"
    assert reseller["hold_reason"] == "NONE"
    assert reseller["suspension_ends_at"] is None
    assert_same_instant(
        reseller["last_suspension_ended_at"], SUSPENSION_ENDS, "last_suspension_ended_at"
    )
    assert reseller["violation_points_total"] == 14

    notice = read_notice(world["notices"][1]["id"])
    assert notice["status"] == "SATISFIED"
    assert notice["closed_reason"] == "SUSPENSION_SERVED"


def test_reseller_suspended_to_authorized_by_rescission_reverses_points():
    """Rescission reinstates and refunds, unlike serving the suspension out.

    PRD: "When the rescinded notice's `rung` was `SUSPENSION` and the reseller is
    currently `SUSPENDED`, the reseller is reinstated in the same operation:
    `authorization_status` back to `AUTHORIZED`, `supply_status` to `OPEN`, `hold_reason`
    to `NONE`, `last_suspension_ended_at` stamped with the current clock,
    `suspension_ends_at` cleared to null, and the reseller's `version` advanced."

    Design: Corner/state_machines/reseller_suspended_to_authorized_by_rescission_reverses_points
    """
    world = _ladder_to_suspension(_authorized_channel())

    rescinded = rescind_notice(world["notices"][1]["id"], reason="Evidence chain incomplete.")

    assert rescinded["status"] == "RESCINDED"

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "AUTHORIZED"
    assert reseller["supply_status"] == "OPEN"
    assert reseller["hold_reason"] == "NONE"
    assert reseller["suspension_ends_at"] is None
    assert_same_instant(
        reseller["last_suspension_ended_at"], CLOCK_AUG_20, "last_suspension_ended_at"
    )
    assert reseller["violation_points_total"] == 3

    violation = read_violation(world["violations"][1]["id"])
    assert violation["status"] == "DETECTED"
    assert violation["assessed_points"] is None
    assert violation["assessed_floor_cents"] is None
    assert violation["cure_deadline_at"] is None


def test_reseller_authorized_or_suspended_to_terminated_closes_open_violations():
    """Both axes reach their terminal pair and the open history is closed moot.

    PRD: "Every violation of that reseller whose status is `DETECTED`, `NOTICED` or
    `DISPUTED` moves to `CLOSED_MOOT` with `resolution_reason` recorded as
    `RESELLER_TERMINATED` and its own `version` advanced — and critically, the
    `assessed_points` on those violations are **retained** in the ledger, because a
    terminated reseller's history is not forgiven."

    Design: Corner/state_machines/reseller_authorized_or_suspended_to_terminated_closes_open_violations
    """
    world = _ladder_to_suspension(_authorized_channel())
    _terminate(world)

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "TERMINATED"
    assert reseller["supply_status"] == "CUT_OFF"
    assert reseller["hold_reason"] == "TERMINATION"
    assert_same_instant(reseller["terminated_at"], CLOCK_AUG_20, "terminated_at")
    assert reseller["suspension_ends_at"] is None
    assert reseller["violation_points_total"] == 19

    for violation, points in ((world["violations"][0], 3), (world["violations"][1], 11)):
        row = read_violation(violation["id"])
        assert row["status"] == "CLOSED_MOOT"
        assert row["resolution_reason"] == "RESELLER_TERMINATED"
        assert row["assessed_points"] == points


def test_reseller_supply_axis_open_to_hold_leaves_authorization_alone():
    """A warehouse hold is a supply-axis-only move by the channel manager.

    PRD: "Placing an `OPEN` reseller on hold moves `OPEN → HOLD` with `hold_reason` set
    to `QUALITY_OBLIGATION`, requires the reseller's `authorization_status` not to be
    `TERMINATED`, and advances the reseller's `version`; the authorization axis is
    untouched, so a reseller sitting on a quality hold is still `AUTHORIZED`."

    Design: Corner/state_machines/reseller_supply_axis_open_to_hold_leaves_authorization_alone
    """
    world = _authorized_channel()

    held = hold_supply(world["reseller"]["id"], hold_reason="QUALITY_OBLIGATION")

    assert held["supply_status"] == "HOLD"
    assert held["hold_reason"] == "QUALITY_OBLIGATION"
    assert held["authorization_status"] == "AUTHORIZED"
    assert held["version"] == 4


def test_reseller_supply_axis_hold_to_open_releases_quality_hold():
    """A quality hold is the kind of hold the warehouse route may lift again.

    PRD: "Releasing a hold moves `HOLD → OPEN` with `hold_reason` reset to `NONE`; it
    requires the reseller to currently be on `HOLD`, requires `hold_reason` to be either
    `QUALITY_OBLIGATION` or `AGREEMENT_EXPIRED`, and requires `authorization_status` to
    be `AUTHORIZED`. It also advances `version`."

    Design: Corner/state_machines/reseller_supply_axis_hold_to_open_releases_quality_hold
    """
    world = _authorized_channel()
    hold_supply(world["reseller"]["id"], hold_reason="QUALITY_OBLIGATION")

    released = release_supply(world["reseller"]["id"])

    assert released["supply_status"] == "OPEN"
    assert released["hold_reason"] == "NONE"
    assert released["authorization_status"] == "AUTHORIZED"
    assert released["version"] == 5
