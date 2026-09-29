"""Declared transitions of the evidence, enforcement and diversion entities.

Observations fork on compliance and on whether the storefront was matched;
violations have three ways out of a notice; exceptions, serialized units, test
purchases and chargebacks each walk their own declared path.  The last group
checks the state every row is born in.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    ANALYST_HEADERS,
    BCM_HEADERS,
    COUNSEL_HEADERS,
    api_client,
)
from test_helpers.assertions import (
    assert_freshly_created,
    assert_same_instant,
    deviation_cents,
    deviation_pct,
    score_delta,
    tier_rate_for_score,
    violation_points,
)
from test_helpers.constants import evidence_hash
from test_helpers.factories import (
    chargeback_dispute_decision_payload,
    chargeback_dispute_payload,
    confirm_outcome_payload,
    cure_submission_payload,
    exception_decision_payload,
    observation_payload,
    product_adjustment_payload,
    serial_capture_payload,
    ship_downstream_payload,
    violation_dispute_decision_payload,
    violation_dispute_payload,
)
from test_helpers.fixtures import (
    acknowledge_notice,
    approve_exception,
    assess_chargeback,
    capture_observation,
    capture_purchase_serial,
    create_active_agreement,
    create_confirmed_trace,
    create_detected_violation,
    create_distributor,
    create_draft_policy,
    create_product,
    create_published_policy,
    create_reseller,
    create_serial_unit,
    issue_notice,
    order_test_purchase,
    pin_clock,
    read_chargeback,
    read_distributor,
    read_exception,
    read_notice,
    read_observation,
    read_product,
    read_reseller,
    read_serial_unit,
    read_violation,
    request_exception,
    rescind_notice,
    run_sweep,
    ship_unit_downstream,
)
from test_helpers.test_users import make_distributor_headers, make_reseller_headers

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
CLOCK_AUG_25 = "2026-08-25T00:00:00Z"
CLOCK_AUG_31 = "2026-08-31T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
OBSERVED_AUG_19 = "2026-08-19T00:00:00Z"
CURE_DEADLINE_AUG_30 = "2026-08-30T00:00:00Z"
CURE_DEADLINE_SEP_04 = "2026-09-04T00:00:00Z"
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
    world["violations"] = [world["violation"], second]
    world["notices"] = [world["notice"], suspension]
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


def _grey_listing(product_id, listed_price_cents=9000, index=3):
    """A below-floor listing that could not be matched to any authorized reseller."""
    return capture_observation(
        product_id,
        listed_price_cents=listed_price_cents,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=evidence_hash(index),
        seller_display_name="GreyBox Deals",
        listing_url="https://marketplace.example/greybox/1",
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


# --------------------------------------------------------------------------- #
# PriceObservation
# --------------------------------------------------------------------------- #
def test_observation_captured_to_evaluated_compliant_writes_zero_deviation():
    """A listing at the floor lands compliant with both deviation fields at zero.

    PRD: "When the effective advertised price is greater than or equal to the resolved
    floor, the observation moves `CAPTURED → EVALUATED_COMPLIANT`. It stores
    `allocated_component_price_cents` (bundles only), `effective_advertised_price_cents`
    and `effective_map_floor_cents`, sets both `deviation_cents` and `deviation_pct` to
    0, advances its own `version`, and creates no violation."

    Design: Corner/state_machines/observation_captured_to_evaluated_compliant_writes_zero_deviation
    """
    world = _authorized_channel()
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        world["product"]["id"],
        listed_price_cents=15000,
        observed_at=OBSERVED_AUG_18,
        matched_reseller_id=world["reseller"]["id"],
        seller_display_name="Acme Store",
    )

    evaluation = validate_success(
        api_client.evaluate_observation(observation["id"], ANALYST_HEADERS)
    )

    assert evaluation["evaluation_status"] == "EVALUATED_COMPLIANT"
    assert evaluation["effective_advertised_price_cents"] == 15000
    assert evaluation["effective_map_floor_cents"] == 15000
    assert evaluation["deviation_cents"] == 0
    assert evaluation["deviation_pct"] == 0
    assert evaluation["violation_id"] is None

    row = read_observation(observation["id"])
    assert row["evaluation_status"] == "EVALUATED_COMPLIANT"
    assert row["version"] == 2

    _rows, meta = validate_paginated(api_client.list_violations(BCM_HEADERS))
    assert meta["total_count"] == 0


def test_observation_captured_to_evaluated_breach_without_match_creates_no_violation():
    """An unmatched breach still records the deviation but opens no violation row.

    PRD: "If `matched_reseller_id` is null, **no** violation row is created at all:
    there is nobody under contract to notice, `unauthorized_seller_confirmed` remains
    false, and the breach is instead routed into the test-purchase workflow of §3.8."

    Design: Corner/state_machines/observation_captured_to_evaluated_breach_without_match_creates_no_violation
    """
    world = _authorized_channel()
    pin_clock(CLOCK_AUG_20)
    observation = _grey_listing(world["product"]["id"])

    evaluation = validate_success(
        api_client.evaluate_observation(observation["id"], ANALYST_HEADERS)
    )

    assert evaluation["evaluation_status"] == "EVALUATED_BREACH"
    assert evaluation["deviation_cents"] == deviation_cents(15000, 9000) == 6000
    assert evaluation["deviation_pct"] == deviation_pct(15000, 6000) == 0.4
    assert evaluation["violation_id"] is None
    assert evaluation["unauthorized_seller_confirmed"] is False

    row = read_observation(observation["id"])
    assert row["evaluation_status"] == "EVALUATED_BREACH"
    assert row["unauthorized_seller_confirmed"] is False

    _rows, meta = validate_paginated(api_client.list_violations(BCM_HEADERS))
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------- #
# Violation
# --------------------------------------------------------------------------- #
def test_violation_detected_to_noticed_sets_assessed_fields_and_cure_deadline():
    """Issuance charges the final points and starts the cure clock.

    PRD: "The violation moves `DETECTED → NOTICED`: its `assessed_floor_cents` and
    `assessed_points` are set from the final recomputation, its `cure_deadline_at` is set
    to the current logical clock plus the cited policy's `cure_window_days`, and its
    `version` is advanced. The reseller's `violation_points_total` is increased by the
    assessed points and the reseller's `version` is advanced."

    Design: Corner/state_machines/violation_detected_to_noticed_sets_assessed_fields_and_cure_deadline
    """
    world = _warned(_authorized_channel())

    assert world["notice"]["rung"] == "WARNING"
    assert world["notice"]["issued_by_user_id"] == "bcm-1"

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "NOTICED"
    assert violation["assessed_floor_cents"] == 15000
    assert violation["assessed_points"] == violation_points(15000, 14000, "MARKETPLACE", 0) == 3
    assert_same_instant(violation["cure_deadline_at"], CURE_DEADLINE_AUG_30, "cure_deadline_at")

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 3


def test_violation_noticed_to_cured_retains_points_and_satisfies_notice():
    """Fixing the listing satisfies the notice without refunding the points.

    PRD: "What curing does **not** do is refund points: the `assessed_points` stay in
    the reseller's `violation_points_total`, because a cured violation still counts
    toward the ladder."

    Design: Corner/state_machines/violation_noticed_to_cured_retains_points_and_satisfies_notice
    """
    world = _warned(_authorized_channel())

    cured = validate_success(
        api_client.submit_cure(
            world["violation"]["id"],
            cure_submission_payload(corrected_price_cents=15000),
            make_reseller_headers(world["reseller"]["id"]),
        )
    )

    assert cured["status"] == "CURED"
    assert cured["resolution_reason"] == "CURE_ACCEPTED"
    assert cured["assessed_points"] == 3

    notice = read_notice(world["notice"]["id"])
    assert notice["status"] == "SATISFIED"
    assert notice["closed_reason"] == "VIOLATION_CURED"

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 3


def test_violation_noticed_to_disputed_stores_reason_without_touching_points():
    """Opening a dispute records the reason and leaves the ledger and counter alone.

    PRD: "Supplying a `dispute_reason` moves the violation `NOTICED → DISPUTED`,
    recording that reason and advancing the violation's `version`; it requires the
    violation to be `NOTICED` and requires `dispute_rounds` to be strictly below 2, else
    `ERR_DISPUTE_ROUNDS_EXHAUSTED`. Note that the dispute itself does not increment
    `dispute_rounds` — that counter tracks disputes that have already been *rejected*."

    Design: Corner/state_machines/violation_noticed_to_disputed_stores_reason_without_touching_points
    """
    world = _warned(_authorized_channel())

    disputed = validate_success(
        api_client.dispute_violation(
            world["violation"]["id"],
            violation_dispute_payload(dispute_reason="The page showed a stale price."),
            make_reseller_headers(world["reseller"]["id"]),
        )
    )

    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_reason"] == "The page showed a stale price."
    assert disputed["dispute_rounds"] == 0
    assert disputed["assessed_points"] == 3
    assert_same_instant(disputed["cure_deadline_at"], CURE_DEADLINE_AUG_30, "cure_deadline_at")

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 3
    assert read_notice(world["notice"]["id"])["status"] == "ISSUED"


def test_violation_disputed_to_noticed_on_reject_extends_cure_deadline_five_days():
    """A rejected round returns the violation to NOTICED with a longer cure window.

    PRD: "A `decision` of `REJECT` moves it `DISPUTED → NOTICED`: `dispute_rounds` is
    increased by one, `cure_deadline_at` is pushed out by a further five days to give the
    reseller a fresh chance to comply, `resolution_reason` is cleared back to null, and
    the violation's `version` is advanced."

    Design: Corner/state_machines/violation_disputed_to_noticed_on_reject_extends_cure_deadline_five_days
    """
    world = _warned(_authorized_channel())
    validate_success(
        api_client.dispute_violation(
            world["violation"]["id"],
            violation_dispute_payload(),
            make_reseller_headers(world["reseller"]["id"]),
        )
    )

    decided = validate_success(
        api_client.decide_violation_dispute(
            world["violation"]["id"],
            violation_dispute_decision_payload("REJECT", decision_reason="Screenshot stands."),
            BCM_HEADERS,
        )
    )

    assert decided["status"] == "NOTICED"
    assert decided["dispute_rounds"] == 1
    assert decided["resolution_reason"] is None
    assert_same_instant(decided["cure_deadline_at"], CURE_DEADLINE_SEP_04, "cure_deadline_at")

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 3


def test_violation_disputed_to_voided_on_sustain_reverses_points_and_rescinds_notice():
    """A sustained dispute is a compensating action: the ledger returns to zero.

    PRD: "A `decision` of `SUSTAIN` moves it `DISPUTED → VOIDED`: `resolution_reason` is
    set to `DISPUTE_SUSTAINED`; the `assessed_points` are subtracted from the reseller's
    `violation_points_total` and then `assessed_points`, `assessed_floor_cents` and
    `cure_deadline_at` are all cleared to null with the reseller's `version` advanced; the
    latest non-rescinded notice for that violation moves to `RESCINDED`, which — when that
    notice's `rung` was `SUSPENSION` — reinstates the reseller as described below; and the
    violation's `version` is advanced."

    Design: Corner/state_machines/violation_disputed_to_voided_on_sustain_reverses_points_and_rescinds_notice
    """
    world = _warned(_authorized_channel())
    validate_success(
        api_client.dispute_violation(
            world["violation"]["id"],
            violation_dispute_payload(),
            make_reseller_headers(world["reseller"]["id"]),
        )
    )

    decided = validate_success(
        api_client.decide_violation_dispute(
            world["violation"]["id"],
            violation_dispute_decision_payload("SUSTAIN", decision_reason="Evidence rebutted."),
            BCM_HEADERS,
        )
    )

    assert decided["status"] == "VOIDED"
    assert decided["resolution_reason"] == "DISPUTE_SUSTAINED"
    assert decided["assessed_points"] is None
    assert decided["assessed_floor_cents"] is None
    assert decided["cure_deadline_at"] is None

    assert read_notice(world["notice"]["id"])["status"] == "RESCINDED"
    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 0


def test_violation_noticed_to_escalated_when_sweep_passes_cure_deadline():
    """Doing nothing until the deadline lapses escalates and keeps the points.

    PRD: "When the sweep observes a violation in `NOTICED` whose `cure_deadline_at` is
    at or before the clock, the violation moves `NOTICED → ESCALATED` with
    `resolution_reason` recorded as `CURE_WINDOW_LAPSED` and its `version` advanced; the
    `assessed_points` are retained in the ledger."

    Design: Corner/state_machines/violation_noticed_to_escalated_when_sweep_passes_cure_deadline
    """
    world = _warned(_authorized_channel())

    pin_clock(CLOCK_AUG_31)
    counters = run_sweep()

    assert counters["escalated_violations"] == 1

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "ESCALATED"
    assert violation["resolution_reason"] == "CURE_WINDOW_LAPSED"
    assert violation["assessed_points"] == 3

    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 3


def test_violation_noticed_to_voided_by_retroactive_exception_approval():
    """A retroactive exception lifts the listing above the floor and voids the case.

    PRD: "Each such violation moves to `VOIDED` with `resolution_reason` recorded as
    `RETROACTIVE_EXCEPTION` and its own `version` advanced; where its `assessed_points`
    was not null, that figure is subtracted from the reseller's `violation_points_total`,
    `assessed_points` is set back to null, and the reseller's `version` is advanced; and
    every enforcement notice for that violation in status `ISSUED` or `ACKNOWLEDGED` is
    moved to `RESCINDED`."

    Design: Corner/state_machines/violation_noticed_to_voided_by_retroactive_exception_approval
    """
    world = _warned(_authorized_channel())
    exception = _requested_exception(world["product"]["id"])
    assert exception["retroactive"] is True

    approved = approve_exception(exception["id"], decision_reason="Marketing plan cleared.")

    assert approved["status"] == "APPROVED"
    assert approved["override_floor_cents"] == 13000
    assert approved["voided_violation_count"] == 1

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "VOIDED"
    assert violation["resolution_reason"] == "RETROACTIVE_EXCEPTION"
    assert violation["assessed_points"] is None

    assert read_notice(world["notice"]["id"])["status"] == "RESCINDED"
    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 0


def test_violation_detected_to_closed_moot_when_reseller_is_terminated():
    """Termination closes a never-noticed violation without charging it points.

    PRD: "Every violation of that reseller whose status is `DETECTED`, `NOTICED` or
    `DISPUTED` moves to `CLOSED_MOOT` with `resolution_reason` recorded as
    `RESELLER_TERMINATED` and its own `version` advanced — and critically, the
    `assessed_points` on those violations are **retained** in the ledger, because a
    terminated reseller's history is not forgiven."

    Design: Corner/state_machines/violation_detected_to_closed_moot_when_reseller_is_terminated
    """
    world = _ladder_to_suspension(
        _authorized_channel(permitted_channels=["MARKETPLACE", "OWN_WEBSITE", "RETAILER_SITE"])
    )
    never_noticed, _obs, _ev = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=12000,
        channel="RETAILER_SITE",
        observed_at=OBSERVED_AUG_19,
        evidence_hash=evidence_hash(3),
        listing_url="https://retailer.example/acme/4",
        seller_display_name="Acme Store",
    )
    assert never_noticed["status"] == "DETECTED"
    assert never_noticed["assessed_points"] is None

    _terminate(world)

    mooted = read_violation(never_noticed["id"])
    assert mooted["status"] == "CLOSED_MOOT"
    assert mooted["resolution_reason"] == "RESELLER_TERMINATED"
    assert mooted["assessed_points"] is None

    warned = read_violation(world["violations"][0]["id"])
    assert warned["status"] == "CLOSED_MOOT"
    assert warned["assessed_points"] == 3

    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 19


# --------------------------------------------------------------------------- #
# EnforcementNotice
# --------------------------------------------------------------------------- #
def test_notice_issued_to_acknowledged_by_the_owning_reseller():
    """Acknowledgement is bookkeeping on the notice row and nothing else.

    PRD: "A reseller may acknowledge a notice, moving it `ISSUED → ACKNOWLEDGED` with
    `acknowledged_at` stamped from the current clock and the notice's `version` advanced.
    Acknowledgement is bookkeeping; it changes nothing about the underlying violation or
    the ladder, but an `ACKNOWLEDGED` notice still counts as served when the rung ceiling
    is computed."

    Design: Corner/state_machines/notice_issued_to_acknowledged_by_the_owning_reseller
    """
    world = _warned(_authorized_channel())
    reseller_version_before = read_reseller(world["reseller"]["id"])["version"]

    acknowledged = validate_success(
        api_client.acknowledge_notice(
            world["notice"]["id"], make_reseller_headers(world["reseller"]["id"])
        )
    )

    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert_same_instant(acknowledged["acknowledged_at"], CLOCK_AUG_20, "acknowledged_at")
    assert acknowledged["version"] == 2

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "NOTICED"
    assert violation["assessed_points"] == 3

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["version"] == reseller_version_before
    assert reseller["violation_points_total"] == 3


def test_notice_acknowledged_to_satisfied_when_the_cited_violation_is_cured():
    """The cure reaches the notice from the violation side, not the reseller's.

    PRD: "It moves the violation `NOTICED → CURED` with `resolution_reason` set to
    `CURE_ACCEPTED` and its `version` advanced, and it moves the latest non-rescinded
    notice for that violation to `SATISFIED` with `closed_reason` recorded as
    `VIOLATION_CURED` and that notice's `version` advanced."

    Design: Corner/state_machines/notice_acknowledged_to_satisfied_when_the_cited_violation_is_cured
    """
    world = _warned(_authorized_channel())
    acknowledged = acknowledge_notice(world["notice"]["id"], world["reseller"]["id"])
    assert acknowledged["status"] == "ACKNOWLEDGED"

    validate_success(
        api_client.submit_cure(
            world["violation"]["id"],
            cure_submission_payload(),
            make_reseller_headers(world["reseller"]["id"]),
        )
    )

    notice = read_notice(world["notice"]["id"])
    assert notice["status"] == "SATISFIED"
    assert notice["closed_reason"] == "VIOLATION_CURED"
    assert notice["version"] == 3
    assert read_violation(world["violation"]["id"])["status"] == "CURED"


def test_notice_issued_to_rescinded_returns_the_violation_to_detected():
    """Rescission unwinds the notice and leaves the evidence noticeable again.

    PRD: "Otherwise the notice moves to `RESCINDED` with `closed_reason` recorded from
    the supplied reason and its `version` advanced, and the reversal reaches back into the
    violation: the cited violation is returned to status `DETECTED` with
    `assessed_points`, `assessed_floor_cents` and `cure_deadline_at` all cleared to null,
    and the notice's `assessed_points` are subtracted from the reseller's
    `violation_points_total`."

    Design: Corner/state_machines/notice_issued_to_rescinded_returns_the_violation_to_detected
    """
    world = _warned(_authorized_channel())

    rescinded = rescind_notice(world["notice"]["id"], reason="Issued on incomplete evidence.")

    assert rescinded["status"] == "RESCINDED"
    assert rescinded["closed_reason"] == "Issued on incomplete evidence."
    assert rescinded["version"] == 2
    assert rescinded["assessed_points"] == 3

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "DETECTED"
    assert violation["assessed_points"] is None
    assert violation["assessed_floor_cents"] is None
    assert violation["cure_deadline_at"] is None

    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 0


# --------------------------------------------------------------------------- #
# PricingException
# --------------------------------------------------------------------------- #
def test_exception_requested_to_approved_raises_open_exception_count():
    """Approval installs the snapshotted floor and counts against the product.

    PRD: "It stamps `approved_by_user_id` and records `decision_reason`. It increases
    the product's `open_exception_count` by one and advances the product's `version`."

    Design: Corner/state_machines/exception_requested_to_approved_raises_open_exception_count
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    product = create_product(policy["id"], name="Studio Headphones")
    exception = _requested_exception(product["id"])
    assert exception["status"] == "REQUESTED"
    assert exception["override_floor_cents"] is None

    approved = validate_success(
        api_client.decide_exception(
            exception["id"],
            exception_decision_payload("APPROVE", decision_reason="Marketing plan cleared."),
            COUNSEL_HEADERS,
        )
    )

    assert approved["status"] == "APPROVED"
    assert approved["override_floor_cents"] == 13000
    assert approved["approved_by_user_id"] == "counsel-1"
    assert approved["decision_reason"] == "Marketing plan cleared."
    assert approved["retroactive"] is False
    assert approved["voided_violation_count"] == 0

    row = read_product(product["id"])
    assert row["open_exception_count"] == 1
    assert row["version"] == 2


def test_exception_requested_to_rejected_leaves_floor_null():
    """A rejected exception installs nothing and never touches the product.

    PRD: "A `decision` of `REJECT` moves it `REQUESTED → REJECTED`, recording
    `decision_reason` and stamping `approved_by_user_id` with the deciding counsel's
    `X-User-ID`, and advances the exception's `version`."

    Design: Corner/state_machines/exception_requested_to_rejected_leaves_floor_null
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    product = create_product(policy["id"], name="Studio Headphones")
    exception = _requested_exception(product["id"])

    rejected = validate_success(
        api_client.decide_exception(
            exception["id"],
            exception_decision_payload("REJECT", decision_reason="No marketing rationale."),
            COUNSEL_HEADERS,
        )
    )

    assert rejected["status"] == "REJECTED"
    assert rejected["override_floor_cents"] is None
    assert rejected["approved_by_user_id"] == "counsel-1"
    assert rejected["decision_reason"] == "No marketing rationale."
    assert rejected["version"] == 2

    row = read_product(product["id"])
    assert row["open_exception_count"] == 0
    assert row["version"] == 1


def test_exception_approved_to_expired_lowers_open_exception_count():
    """Expiry is a sweep consequence that decrements the product's counter again.

    PRD: "When the sweep observes that `ends_at` is at or before the clock, the
    exception moves `APPROVED → EXPIRED`, the product's `open_exception_count` is reduced
    by one with the product's `version` advanced, and the exception's `version` is
    advanced."

    Design: Corner/state_machines/exception_approved_to_expired_lowers_open_exception_count
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    product = create_product(policy["id"], name="Studio Headphones")
    exception = _requested_exception(product["id"])
    approve_exception(exception["id"])

    pin_clock(CLOCK_AUG_25)
    counters = run_sweep()

    assert counters["expired_exceptions"] == 1

    row = read_exception(exception["id"])
    assert row["status"] == "EXPIRED"
    assert row["version"] == 3

    product_row = read_product(product["id"])
    assert product_row["open_exception_count"] == 0
    assert product_row["version"] == 3


def test_exception_approved_to_voided_when_product_is_discontinued():
    """Discontinuing the product voids its live exceptions in the same cascade.

    PRD: "Setting `lifecycle_status` to `DISCONTINUED`, however, triggers a cascade:
    every pricing exception on that product in status `REQUESTED` or `APPROVED` moves to
    `VOIDED` with its `decision_reason` recorded as `PRODUCT_DISCONTINUED` and its own
    `version` advanced; where the exception was previously `APPROVED`, the product's
    `open_exception_count` is reduced by one as part of the same cascade."

    Design: Corner/state_machines/exception_approved_to_voided_when_product_is_discontinued
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    product = create_product(policy["id"], name="Studio Headphones")
    exception = _requested_exception(product["id"])
    approve_exception(exception["id"])

    adjusted = validate_success(
        api_client.adjust_product(
            product["id"],
            product_adjustment_payload(lifecycle_status="DISCONTINUED"),
            BCM_HEADERS,
        )
    )

    assert adjusted["lifecycle_status"] == "DISCONTINUED"
    assert adjusted["open_exception_count"] == 0

    row = read_exception(exception["id"])
    assert row["status"] == "VOIDED"
    assert row["decision_reason"] == "PRODUCT_DISCONTINUED"
    assert row["version"] == 3


# --------------------------------------------------------------------------- #
# SerialUnit
# --------------------------------------------------------------------------- #
def test_serial_unit_shipped_to_distributor_to_shipped_to_reseller():
    """The distributor records the next custody hop on its own units.

    PRD: "Supplying a `downstream_reseller_id` moves a unit
    `SHIPPED_TO_DISTRIBUTOR → SHIPPED_TO_RESELLER`, setting `downstream_reseller_id` and
    stamping `shipped_downstream_at` with the current clock, and advancing the unit's
    `version`."

    Design: Corner/state_machines/serial_unit_shipped_to_distributor_to_shipped_to_reseller
    """
    world = _authorized_channel()
    distributor = create_distributor(legal_name="Northwind Distribution")
    unit = create_serial_unit(world["product"]["id"], distributor["id"], lot_code="LOT-A")
    assert unit["status"] == "SHIPPED_TO_DISTRIBUTOR"

    shipped = validate_success(
        api_client.ship_downstream(
            unit["id"],
            ship_downstream_payload(world["reseller"]["id"]),
            make_distributor_headers(distributor["id"]),
        )
    )

    assert shipped["status"] == "SHIPPED_TO_RESELLER"
    assert shipped["downstream_reseller_id"] == world["reseller"]["id"]
    assert_same_instant(shipped["shipped_downstream_at"], CLOCK_AUG_01, "shipped_downstream_at")
    assert shipped["version"] == 2


def test_serial_unit_to_traced_unauthorized_flags_downstream_reseller_for_review():
    """A confirmed trace moves the unit and raises the downstream review flag.

    PRD: "It also reaches into two other rows: the linked observation has
    `unauthorized_seller_confirmed` set to true with its `version` advanced, and the
    traced unit moves from `SHIPPED_TO_DISTRIBUTOR` or `SHIPPED_TO_RESELLER` to
    `TRACED_UNAUTHORIZED` with `traced_at` stamped from the current clock and its own
    `version` advanced. Where that unit has a non-null `downstream_reseller_id`, the
    affected reseller's `review_required` flag is recomputed per §2.11 and its `version`
    advanced only if the value actually changed."

    Design: Corner/state_machines/serial_unit_to_traced_unauthorized_flags_downstream_reseller_for_review
    """
    world = _authorized_channel()
    distributor = create_distributor(legal_name="Northwind Distribution")
    unit = create_serial_unit(world["product"]["id"], distributor["id"], lot_code="LOT-A")
    unit = ship_unit_downstream(unit["id"], distributor["id"], world["reseller"]["id"])
    assert read_reseller(world["reseller"]["id"])["review_required"] is False

    pin_clock(CLOCK_AUG_20)
    observation = _grey_listing(world["product"]["id"])
    purchase = order_test_purchase(observation["id"], ordered_at=OBSERVED_AUG_19)
    capture_purchase_serial(purchase["id"], unit["serial_number"])
    validate_success(
        api_client.confirm_outcome(
            purchase["id"], confirm_outcome_payload("UNAUTHORIZED"), ANALYST_HEADERS
        )
    )

    traced = read_serial_unit(unit["id"])
    assert traced["status"] == "TRACED_UNAUTHORIZED"
    assert_same_instant(traced["traced_at"], CLOCK_AUG_20, "traced_at")
    assert traced["downstream_reseller_id"] == world["reseller"]["id"]

    assert read_observation(observation["id"])["unauthorized_seller_confirmed"] is True
    assert read_reseller(world["reseller"]["id"])["review_required"] is True


def test_serial_unit_shipped_to_reseller_to_recalled_on_agreement_termination():
    """RECALLED is reachable only through the terminated agreement.

    PRD: "A serialized unit reaches `RECALLED` only through the agreement-termination
    cascade of §3.4, and `RECALLED` is its single terminal state."

    Design: Corner/state_machines/serial_unit_shipped_to_reseller_to_recalled_on_agreement_termination
    """
    world = _authorized_channel()
    distributor = create_distributor(legal_name="Northwind Distribution")
    unit = create_serial_unit(world["product"]["id"], distributor["id"], lot_code="LOT-A")
    unit = ship_unit_downstream(unit["id"], distributor["id"], world["reseller"]["id"])

    _ladder_to_suspension(world)
    termination = _terminate(world)
    assert termination["rung"] == "TERMINATION"

    recalled = read_serial_unit(unit["id"])
    assert recalled["status"] == "RECALLED"
    assert recalled["downstream_reseller_id"] == world["reseller"]["id"]
    assert recalled["version"] == 3


# --------------------------------------------------------------------------- #
# TestPurchase
# --------------------------------------------------------------------------- #
def test_test_purchase_ordered_to_serial_captured_links_the_unit():
    """Capturing the serial resolves it to the registered unit without moving it.

    PRD: "Supplying a `serial_number` moves the purchase `ORDERED → SERIAL_CAPTURED`,
    storing that value as `captured_serial_number` and resolving it to a
    `traced_serial_unit_id`, and advancing the purchase's `version`."

    Design: Corner/state_machines/test_purchase_ordered_to_serial_captured_links_the_unit
    """
    world = _authorized_channel()
    distributor = create_distributor(legal_name="Northwind Distribution")
    unit = create_serial_unit(world["product"]["id"], distributor["id"], lot_code="LOT-A")

    pin_clock(CLOCK_AUG_20)
    observation = _grey_listing(world["product"]["id"])
    purchase = order_test_purchase(observation["id"], ordered_at=OBSERVED_AUG_19)
    assert purchase["status"] == "ORDERED"

    captured = validate_success(
        api_client.capture_serial(
            purchase["id"], serial_capture_payload(unit["serial_number"]), ANALYST_HEADERS
        )
    )

    assert captured["status"] == "SERIAL_CAPTURED"
    assert captured["captured_serial_number"] == unit["serial_number"]
    assert captured["traced_serial_unit_id"] == unit["id"]
    assert captured["version"] == 2

    assert read_serial_unit(unit["id"])["status"] == "SHIPPED_TO_DISTRIBUTOR"


def test_test_purchase_serial_captured_to_confirmed_unauthorized_traces_the_unit():
    """Confirming the finding is a three-row write ending in a traced unit.

    PRD: "An `outcome` of `UNAUTHORIZED` moves the purchase
    `SERIAL_CAPTURED → CONFIRMED_UNAUTHORIZED`; it requires `traced_serial_unit_id` to be
    non-null, records `outcome_reason`, and advances the purchase's `version`."

    Design: Corner/state_machines/test_purchase_serial_captured_to_confirmed_unauthorized_traces_the_unit
    """
    world = _authorized_channel()
    distributor = create_distributor(legal_name="Northwind Distribution")
    unit = create_serial_unit(world["product"]["id"], distributor["id"], lot_code="LOT-A")

    pin_clock(CLOCK_AUG_20)
    observation = _grey_listing(world["product"]["id"])
    purchase = order_test_purchase(observation["id"], ordered_at=OBSERVED_AUG_19)
    capture_purchase_serial(purchase["id"], unit["serial_number"])

    confirmed = validate_success(
        api_client.confirm_outcome(
            purchase["id"],
            confirm_outcome_payload("UNAUTHORIZED", outcome_reason="Seller holds no agreement."),
            ANALYST_HEADERS,
        )
    )

    assert confirmed["status"] == "CONFIRMED_UNAUTHORIZED"
    assert confirmed["outcome_reason"] == "Seller holds no agreement."
    assert confirmed["traced_serial_unit_id"] == unit["id"]
    assert confirmed["version"] == 3

    traced = read_serial_unit(unit["id"])
    assert traced["status"] == "TRACED_UNAUTHORIZED"
    assert_same_instant(traced["traced_at"], CLOCK_AUG_20, "traced_at")
    assert read_observation(observation["id"])["unauthorized_seller_confirmed"] is True


def test_test_purchase_serial_captured_to_cleared_leaves_unit_and_observation_alone():
    """Clearing the seller advances the purchase alone.

    PRD: "An `outcome` of `AUTHORIZED` moves the purchase `SERIAL_CAPTURED → CLEARED`,
    recording `outcome_reason` and advancing only the purchase's own `version`; the traced
    unit and the observation are left entirely untouched."

    Design: Corner/state_machines/test_purchase_serial_captured_to_cleared_leaves_unit_and_observation_alone
    """
    world = _authorized_channel()
    distributor = create_distributor(legal_name="Northwind Distribution")
    unit = create_serial_unit(world["product"]["id"], distributor["id"], lot_code="LOT-A")

    pin_clock(CLOCK_AUG_20)
    observation = _grey_listing(world["product"]["id"])
    purchase = order_test_purchase(observation["id"], ordered_at=OBSERVED_AUG_19)
    capture_purchase_serial(purchase["id"], unit["serial_number"])

    cleared = validate_success(
        api_client.confirm_outcome(
            purchase["id"],
            confirm_outcome_payload("AUTHORIZED", outcome_reason="Seller is authorized after all."),
            ANALYST_HEADERS,
        )
    )

    assert cleared["status"] == "CLEARED"
    assert cleared["outcome_reason"] == "Seller is authorized after all."
    assert cleared["version"] == 3

    untouched_unit = read_serial_unit(unit["id"])
    assert untouched_unit["status"] == "SHIPPED_TO_DISTRIBUTOR"
    assert untouched_unit["traced_at"] is None
    assert untouched_unit["version"] == 1

    untouched_observation = read_observation(observation["id"])
    assert untouched_observation["unauthorized_seller_confirmed"] is False
    assert untouched_observation["version"] == 1


# --------------------------------------------------------------------------- #
# DistributorChargeback
# --------------------------------------------------------------------------- #
def _assessed_chargeback(diverted_units=4):
    """A four-unit chargeback against the distributor that shipped the traced unit."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    product = create_product(policy["id"], name="Studio Headphones")
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    purchase, unit, _observation = create_confirmed_trace(
        product["id"], distributor["id"], lot_code="LOT-A"
    )
    chargeback = assess_chargeback(distributor["id"], purchase["id"], diverted_units=diverted_units)
    return {
        "product": product,
        "distributor": distributor,
        "purchase": purchase,
        "unit": unit,
        "chargeback": chargeback,
    }


def test_chargeback_assessed_to_disputed_by_the_owning_distributor():
    """The distributor pushes back and neither ledger moves.

    PRD: "Supplying a `dispute_reason` moves a chargeback `ASSESSED → DISPUTED` or
    `UPHELD → DISPUTED`, recording that reason and advancing the chargeback's `version`;
    it requires the chargeback to be in `ASSESSED` or `UPHELD`, requires `dispute_rounds`
    to be strictly below 2 (else `ERR_DISPUTE_ROUNDS_EXHAUSTED`), and requires the acting
    distributor's `X-User-ID` to equal the chargeback's `distributor_id`."

    Design: Corner/state_machines/chargeback_assessed_to_disputed_by_the_owning_distributor
    """
    world = _assessed_chargeback()
    assert world["chargeback"]["status"] == "ASSESSED"
    assert world["chargeback"]["tier_rate_cents_per_unit"] == tier_rate_for_score(0) == 2500
    assert world["chargeback"]["amount_cents"] == 2500 * 4 == 10000
    assert world["chargeback"]["score_delta_applied"] == score_delta(4) == 10.0

    disputed = validate_success(
        api_client.dispute_chargeback(
            world["chargeback"]["id"],
            chargeback_dispute_payload(dispute_reason="Units left under another lot."),
            make_distributor_headers(world["distributor"]["id"]),
        )
    )

    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_reason"] == "Units left under another lot."
    assert disputed["dispute_rounds"] == 0
    assert disputed["version"] == 2

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 10000
    assert distributor["diversion_score"] == 10.0
    assert distributor["standing"] == "PROBATION"


def test_chargeback_disputed_to_upheld_keeps_the_money_and_bumps_rounds():
    """Upholding leaves both running ledgers exactly where they were.

    PRD: "A `decision` of `UPHOLD` moves it `DISPUTED → UPHELD`: `dispute_rounds` is
    increased by one, `decision_reason` is recorded, the chargeback's `version` is
    advanced, and both ledgers are left exactly as they are — the `amount_cents` stays in
    the distributor's balance and the `score_delta_applied` stays in its diversion score."

    Design: Corner/state_machines/chargeback_disputed_to_upheld_keeps_the_money_and_bumps_rounds
    """
    world = _assessed_chargeback()
    validate_success(
        api_client.dispute_chargeback(
            world["chargeback"]["id"],
            chargeback_dispute_payload(),
            make_distributor_headers(world["distributor"]["id"]),
        )
    )

    upheld = validate_success(
        api_client.decide_chargeback_dispute(
            world["chargeback"]["id"],
            chargeback_dispute_decision_payload("UPHOLD", decision_reason="Shipping records match."),
            COUNSEL_HEADERS,
        )
    )

    assert upheld["status"] == "UPHELD"
    assert upheld["dispute_rounds"] == 1
    assert upheld["decision_reason"] == "Shipping records match."
    assert upheld["version"] == 3

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 10000
    assert distributor["diversion_score"] == 10.0
    assert distributor["standing"] == "PROBATION"


def test_chargeback_disputed_to_reversed_restores_balance_score_and_standing():
    """Reversal is exact and lets probation fall back to good standing.

    PRD: "A `decision` of `REVERSE` moves it `DISPUTED → REVERSED`, its single terminal
    state: `decision_reason` is recorded, the chargeback's `version` is advanced,
    `amount_cents` is subtracted from the distributor's `chargeback_balance_cents`,
    `score_delta_applied` is subtracted from its `diversion_score`, `standing` is
    re-derived from the restored score with the distributor's `version` advanced, and —
    because a standing that falls back from `PROBATION` to `GOOD` changes who is under
    review — the `review_required` flag is recomputed for every reseller whose
    `sourcing_distributor_id` names this distributor, with each changed reseller's
    `version` advanced."

    Design: Corner/state_machines/chargeback_disputed_to_reversed_restores_balance_score_and_standing
    """
    world = _assessed_chargeback()
    validate_success(
        api_client.dispute_chargeback(
            world["chargeback"]["id"],
            chargeback_dispute_payload(),
            make_distributor_headers(world["distributor"]["id"]),
        )
    )

    reversed_row = validate_success(
        api_client.decide_chargeback_dispute(
            world["chargeback"]["id"],
            chargeback_dispute_decision_payload("REVERSE", decision_reason="Lot was mislabelled."),
            COUNSEL_HEADERS,
        )
    )

    assert reversed_row["status"] == "REVERSED"
    assert reversed_row["decision_reason"] == "Lot was mislabelled."
    assert reversed_row["version"] == 3

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 0
    assert distributor["diversion_score"] == 0
    assert distributor["standing"] == "GOOD"

    audited = read_chargeback(world["chargeback"]["id"])
    assert audited["amount_cents"] == 10000
    assert audited["score_delta_applied"] == 10.0


# --------------------------------------------------------------------------- #
# Initial states
# --------------------------------------------------------------------------- #
def test_policy_initial_state_is_draft_at_revision_one():
    """A new policy document is born in DRAFT with every stamp still null.

    PRD: "The new policy is born in status `DRAFT` with `revision_number` set to 1, and
    its `effective_from`, `legal_review_notes`, `reviewed_by_user_id`,
    `published_by_user_id`, `superseded_by_policy_id` and `withdrawn_reason` all null."

    Design: Corner/state_machines/policy_initial_state_is_draft_at_revision_one
    """
    pin_clock(CLOCK_AUG_01)

    policy = create_draft_policy()

    assert policy["status"] == "DRAFT"
    assert policy["revision_number"] == 1
    for field in (
        "effective_from",
        "legal_review_notes",
        "reviewed_by_user_id",
        "published_by_user_id",
        "superseded_by_policy_id",
        "withdrawn_reason",
    ):
        assert policy[field] is None, f"{field} should start null"
    assert_freshly_created(policy)


def test_reseller_initial_state_is_applied_on_both_parallel_axes():
    """An application starts APPLIED on one axis and held on the other.

    PRD: "A newly recorded reseller starts with `authorization_status` `APPLIED`,
    `supply_status` `HOLD`, `hold_reason` `PENDING_AUTHORIZATION`,
    `violation_points_total` at 0 and `review_required` evaluated once at creation (which
    for a fresh row means false unless the named sourcing distributor is already in
    `PROBATION` or `SUSPENDED`). The fields `suspension_ends_at`,
    `last_suspension_ended_at` and `terminated_at` all start null."

    Design: Corner/state_machines/reseller_initial_state_is_applied_on_both_parallel_axes
    """
    pin_clock(CLOCK_AUG_01)

    reseller = create_reseller(legal_name="Acme Retail LLC", contact_email="ops@acme.example")

    assert reseller["authorization_status"] == "APPLIED"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "PENDING_AUTHORIZATION"
    assert reseller["violation_points_total"] == 0
    assert reseller["review_required"] is False
    assert reseller["sourcing_distributor_id"] is None
    assert reseller["suspension_ends_at"] is None
    assert reseller["last_suspension_ended_at"] is None
    assert reseller["terminated_at"] is None
    assert_freshly_created(reseller)


def test_observation_initial_state_is_captured_with_null_derived_fields():
    """Capture stores evidence only; every computed money field waits for evaluation.

    PRD: "The row is created with `evaluation_status` `CAPTURED`,
    `unauthorized_seller_confirmed` false, `evidence_captured_by_user_id` stamped from the
    capturing analyst's `X-User-ID`, and all five computed money fields —
    `allocated_component_price_cents`, `effective_advertised_price_cents`,
    `effective_map_floor_cents`, `deviation_cents` and `deviation_pct` — still null."

    Design: Corner/state_machines/observation_initial_state_is_captured_with_null_derived_fields
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    product = create_product(policy["id"], name="Studio Headphones")

    observation = validate_success(
        api_client.create_observation(
            observation_payload(product["id"], listed_price_cents=14000, observed_at=CLOCK_AUG_01),
            ANALYST_HEADERS,
        ),
        201,
    )

    assert observation["evaluation_status"] == "CAPTURED"
    assert observation["unauthorized_seller_confirmed"] is False
    assert observation["evidence_captured_by_user_id"] == "analyst-1"
    for field in (
        "allocated_component_price_cents",
        "effective_advertised_price_cents",
        "effective_map_floor_cents",
        "deviation_cents",
        "deviation_pct",
    ):
        assert observation[field] is None, f"{field} should start null"
    assert_freshly_created(observation)
