"""Layers that stack on top of one another inside a single enforcement request.

A notice issuance is simultaneously a rate threshold (the two points thresholds), a
multi-row cascade (violation, reseller, agreement, units), an optimistic-concurrency
checkpoint (the reseller version token) and a derived-aggregate update (the points
ledger).  Each test below drives the public endpoints up to the interesting instant
and then checks the figure the PRD pins for one of those layers.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import BCM_HEADERS, COUNSEL_HEADERS, api_client
from test_helpers.assertions import (
    assert_reseller_points_reconcile,
    deviation_cents,
    deviation_pct,
    issued_rung,
    score_delta,
    tier_rate_for_score,
    violation_points,
)
from test_helpers.constants import EVIDENCE_HASH_2, EVIDENCE_HASH_3, EVIDENCE_HASH_4
from test_helpers.factories import chargeback_payload, notice_payload
from test_helpers.fixtures import (
    capture_observation,
    capture_purchase_serial,
    confirm_unauthorized,
    create_authorized_reseller,
    create_countersigned_agreement,
    create_detected_violation,
    create_distributor,
    create_product,
    create_published_policy,
    create_reseller,
    create_serial_unit,
    current_distributor_version,
    current_reseller_version,
    issue_notice,
    order_test_purchase,
    pin_clock,
    read_agreement,
    read_distributor,
    read_notice,
    read_reseller,
    read_serial_unit,
    read_violation,
    rescind_notice,
    ship_unit_downstream,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
OBSERVED_AUG_17 = "2026-08-17T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
OBSERVED_AUG_19 = "2026-08-19T00:00:00Z"
SUSPENSION_STARTS = "2026-09-01T00:00:00Z"
SUSPENSION_ENDS = "2026-09-10T00:00:00Z"
SECOND_SUSPENSION_STARTS = "2026-09-05T00:00:00Z"
SECOND_SUSPENSION_ENDS = "2026-09-15T00:00:00Z"
STANDARD_FLOOR = 15000


# --------------------------------------------------------------------------- #
# Shared spine — a marketplace reseller walked up the ladder under a policy whose
# suspension threshold the test chooses.
# --------------------------------------------------------------------------- #
def _setup_ladder_ledger_at_three(suspension_points_threshold):
    """One WARNING worth three points, plus a second detected breach worth four."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(
        suspension_points_threshold=suspension_points_threshold,
        termination_points_threshold=12,
        cure_window_days=10,
        suspension_cooling_off_days=14,
    )
    product = create_product(policy["id"])
    reseller, agreement = create_authorized_reseller(policy["id"])

    pin_clock(CLOCK_AUG_20)
    first_violation, _observation, _evaluation = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_17,
        listing_url="https://marketplace.example/ladder-1",
    )
    first_notice = issue_notice(reseller["id"], first_violation["id"])
    second_violation, _observation2, _evaluation2 = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_2,
        listing_url="https://marketplace.example/ladder-2",
    )
    return {
        "policy": policy,
        "product": product,
        "reseller": reseller,
        "agreement": agreement,
        "first_violation": first_violation,
        "first_notice": first_notice,
        "second_violation": second_violation,
    }


def _issue_suspension_on_second_violation(world, **overrides):
    """Issue the second notice with a suspension window attached."""
    reseller_id = world["reseller"]["id"]
    payload = notice_payload(
        reseller_id,
        world["second_violation"]["id"],
        current_reseller_version(reseller_id),
        suspension_starts_at=SUSPENSION_STARTS,
        suspension_ends_at=SUSPENSION_ENDS,
        **overrides,
    )
    return api_client.issue_notice(payload, BCM_HEADERS)


# --------------------------------------------------------------------------- #
# Instance — layer_rate_cumulative_threshold_exactly_at_suspension_boundary
# --------------------------------------------------------------------------- #
def test_cumulative_seven_against_a_seven_point_threshold_installs_suspension():
    """The threshold comparison is inclusive at the lower bound, so seven suspends.

    PRD: "Compare that figure against the cited policy's two thresholds, with both
    boundaries inclusive at the lower bound: the points-justified rung is `WARNING` when
    the cumulative figure is strictly below `suspension_points_threshold`, `SUSPENSION`
    when it is at or above `suspension_points_threshold` but strictly below
    `termination_points_threshold`, and `TERMINATION` when it is at or above
    `termination_points_threshold`."

    Design: Corner/cross_cutting_complexity_layers/layer_rate_cumulative_threshold_exactly_at_suspension_boundary
    """
    world = _setup_ladder_ledger_at_three(7)
    assert world["first_notice"]["rung"] == "WARNING"
    assert world["first_notice"]["cumulative_points_at_issue"] == 3

    notice = validate_success(
        _issue_suspension_on_second_violation(world, rung="SUSPENSION"), expected_status=201
    )
    assert notice["assessed_points"] == violation_points(
        STANDARD_FLOOR, 14000, "MARKETPLACE", 1
    ) == 4
    assert notice["cumulative_points_at_issue"] == 7
    assert notice["rung"] == issued_rung(7, 7, 12, 1) == "SUSPENSION"

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 7
    assert reseller["authorization_status"] == "SUSPENDED"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "SUSPENSION"


# --------------------------------------------------------------------------- #
# Instance — layer_rate_cumulative_threshold_one_point_below_suspension
# --------------------------------------------------------------------------- #
def test_the_same_seven_point_ledger_stays_on_warning_at_a_threshold_of_eight():
    """One point short of the configured threshold is still only a warning.

    PRD: "Compare that figure against the cited policy's two thresholds, with both
    boundaries inclusive at the lower bound: the points-justified rung is `WARNING` when
    the cumulative figure is strictly below `suspension_points_threshold`, `SUSPENSION`
    when it is at or above `suspension_points_threshold` but strictly below
    `termination_points_threshold`, and `TERMINATION` when it is at or above
    `termination_points_threshold`."

    Design: Corner/cross_cutting_complexity_layers/layer_rate_cumulative_threshold_one_point_below_suspension
    """
    world = _setup_ladder_ledger_at_three(8)
    reseller_id = world["reseller"]["id"]

    notice = validate_success(
        api_client.issue_notice(
            notice_payload(
                reseller_id,
                world["second_violation"]["id"],
                current_reseller_version(reseller_id),
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )
    assert notice["assessed_points"] == violation_points(
        STANDARD_FLOOR, 14000, "MARKETPLACE", 1
    ) == 4
    assert notice["cumulative_points_at_issue"] == 7
    assert notice["rung"] == issued_rung(7, 8, 12, 1) == "WARNING"

    reseller = read_reseller(reseller_id)
    assert reseller["violation_points_total"] == 7
    assert reseller["authorization_status"] == "AUTHORIZED"
    assert reseller["supply_status"] == "OPEN"


# --------------------------------------------------------------------------- #
# Instance — layer_rate_instantaneous_deviation_tier_at_five_percent
# --------------------------------------------------------------------------- #
def _setup_authorized_marketplace_seller():
    """A published policy, a 15000-floor product and one AUTHORIZED marketplace seller."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(policy["id"])
    reseller, agreement = create_authorized_reseller(policy["id"])
    pin_clock(CLOCK_AUG_20)
    return {"policy": policy, "product": product, "reseller": reseller, "agreement": agreement}


def test_a_deviation_of_exactly_five_percent_stays_in_the_first_severity_tier():
    """The 0.0500 tier bound is inclusive, so 14250 earns the one-point base.

    PRD: "Otherwise take the deviation fraction to four decimal places and read the base
    points off four inclusive tiers: 1 point when the fraction is at most 0.0500, 2
    points when it is at most 0.1500, 4 points when it is at most 0.3000, and 6 points
    when it exceeds 0.3000."

    Design: Corner/cross_cutting_complexity_layers/layer_rate_instantaneous_deviation_tier_at_five_percent
    """
    world = _setup_authorized_marketplace_seller()
    violation, _observation, evaluation = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14250,
        observed_at=OBSERVED_AUG_18,
        listing_url="https://marketplace.example/tier-14250",
    )

    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 14250) == 750
    assert evaluation["deviation_pct"] == deviation_pct(STANDARD_FLOOR, 750) == 0.05
    assert evaluation["provisional_points"] == violation_points(
        STANDARD_FLOOR, 14250, "MARKETPLACE", 0
    ) == 2
    assert violation["provisional_floor_cents"] == STANDARD_FLOOR
    assert violation["provisional_points"] == 2


def test_one_cent_further_below_the_floor_tips_into_the_second_severity_tier():
    """A fraction of 0.0501 is past the first bound and doubles the base points.

    PRD: "Otherwise take the deviation fraction to four decimal places and read the base
    points off four inclusive tiers: 1 point when the fraction is at most 0.0500, 2
    points when it is at most 0.1500, 4 points when it is at most 0.3000, and 6 points
    when it exceeds 0.3000."

    Design: Corner/cross_cutting_complexity_layers/layer_rate_instantaneous_deviation_tier_at_five_percent
    """
    world = _setup_authorized_marketplace_seller()
    violation, _observation, evaluation = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14249,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_2,
        listing_url="https://marketplace.example/tier-14249",
    )

    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 14249) == 751
    assert evaluation["deviation_pct"] == deviation_pct(STANDARD_FLOOR, 751) == 0.0501
    assert evaluation["provisional_points"] == violation_points(
        STANDARD_FLOOR, 14249, "MARKETPLACE", 0
    ) == 3
    assert violation["provisional_floor_cents"] == STANDARD_FLOOR


# --------------------------------------------------------------------------- #
# Instance — layer_rate_threshold_resets_after_the_suspension_is_rescinded
# --------------------------------------------------------------------------- #
def _setup_suspended_at_seven():
    """The seven-point ledger of the boundary case, with the suspension already served out."""
    world = _setup_ladder_ledger_at_three(7)
    world["second_notice"] = validate_success(
        _issue_suspension_on_second_violation(world), expected_status=201
    )
    return world


def test_rescinding_the_suspension_notice_rewinds_both_counters_the_ladder_reads():
    """The ledger drops back to three and the cited violation returns to DETECTED.

    PRD: "Otherwise the notice moves to `RESCINDED` with `closed_reason` recorded from
    the supplied reason and its `version` advanced, and the reversal reaches back into
    the violation: the cited violation is returned to status `DETECTED` with
    `assessed_points`, `assessed_floor_cents` and `cure_deadline_at` all cleared to null,
    and the notice's `assessed_points` are subtracted from the reseller's
    `violation_points_total`."

    Design: Corner/cross_cutting_complexity_layers/layer_rate_threshold_resets_after_the_suspension_is_rescinded
    """
    world = _setup_suspended_at_seven()
    assert world["second_notice"]["rung"] == "SUSPENSION"

    rescinded = validate_success(
        api_client.rescind_notice(
            world["second_notice"]["id"],
            {"rescinded_reason": "Second listing was a stale marketplace cache."},
            COUNSEL_HEADERS,
        )
    )
    assert rescinded["status"] == "RESCINDED"

    violation = read_violation(world["second_violation"]["id"])
    assert violation["status"] == "DETECTED"
    assert violation["assessed_points"] is None
    assert violation["assessed_floor_cents"] is None
    assert violation["cure_deadline_at"] is None

    reseller = assert_reseller_points_reconcile(
        api_client, world["reseller"]["id"], BCM_HEADERS
    )
    assert reseller["violation_points_total"] == 3


def test_the_rescinded_violation_can_be_noticed_again_at_the_same_suspension_rung():
    """A rescinded notice is ignored by the ceiling, so the same rung is available again.

    PRD: "Independently, find the highest rung the reseller has already been served: rank
    the rungs so that `WARNING` is first, `SUSPENSION` second and `TERMINATION` third, and
    take the highest rank appearing among that reseller's notices whose `status` is
    `ISSUED`, `ACKNOWLEDGED` or `SATISFIED`; notices in `RESCINDED` are ignored entirely,
    and if no qualifying notice exists the highest served rank is treated as zero."

    Design: Corner/cross_cutting_complexity_layers/layer_rate_threshold_resets_after_the_suspension_is_rescinded
    """
    world = _setup_suspended_at_seven()
    rescind_notice(
        world["second_notice"]["id"], reason="Second listing was a stale marketplace cache."
    )
    reseller_id = world["reseller"]["id"]

    replacement = validate_success(
        api_client.issue_notice(
            notice_payload(
                reseller_id,
                world["second_violation"]["id"],
                current_reseller_version(reseller_id),
                suspension_starts_at=SECOND_SUSPENSION_STARTS,
                suspension_ends_at=SECOND_SUSPENSION_ENDS,
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )
    assert replacement["assessed_points"] == 4
    assert replacement["cumulative_points_at_issue"] == 7
    assert replacement["rung"] == issued_rung(7, 7, 12, 1) == "SUSPENSION"
    assert read_reseller(reseller_id)["violation_points_total"] == 7


# --------------------------------------------------------------------------- #
# Shared spine — the reseller carried to the brink of termination, with a unit in
# its warehouse and a fourth breach still merely detected.
# --------------------------------------------------------------------------- #
def _setup_acme_suspended_at_fourteen(with_spare_violation=False):
    """A SUSPENDED reseller at fourteen points, one shipped unit and a third breach."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(policy["id"])
    distributor = create_distributor(legal_name="Northwind Distribution Cascade")
    reseller, agreement = create_authorized_reseller(policy["id"])
    unit = create_serial_unit(
        product["id"], distributor["id"], serial_number="SN-0002", lot_code="LOT-A"
    )
    unit = ship_unit_downstream(unit["id"], distributor["id"], reseller["id"])

    pin_clock(CLOCK_AUG_20)
    first_violation, _o1, _e1 = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        listing_url="https://marketplace.example/acme-1",
    )
    first_notice = issue_notice(reseller["id"], first_violation["id"])
    second_violation, _o2, _e2 = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_3,
        listing_url="https://marketplace.example/acme-2",
    )
    second_notice = issue_notice(
        reseller["id"],
        second_violation["id"],
        suspension_starts_at=SUSPENSION_STARTS,
        suspension_ends_at=SUSPENSION_ENDS,
    )
    third_violation, _o3, _e3 = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_19,
        evidence_hash=EVIDENCE_HASH_4,
        listing_url="https://marketplace.example/acme-3",
    )
    spare_violation = None
    if with_spare_violation:
        spare_violation, _o4, _e4 = create_detected_violation(
            product["id"],
            reseller["id"],
            listed_price_cents=13000,
            observed_at=OBSERVED_AUG_19,
            listing_url="https://marketplace.example/acme-spare",
        )
    return {
        "policy": policy,
        "product": product,
        "distributor": distributor,
        "reseller": reseller,
        "agreement": agreement,
        "unit": unit,
        "first_violation": first_violation,
        "first_notice": first_notice,
        "second_violation": second_violation,
        "second_notice": second_notice,
        "third_violation": third_violation,
        "spare_violation": spare_violation,
    }


def _terminate(world):
    """Counsel issues the third notice, which the ladder computes as TERMINATION."""
    reseller_id = world["reseller"]["id"]
    return api_client.issue_notice(
        notice_payload(
            reseller_id,
            world["third_violation"]["id"],
            current_reseller_version(reseller_id),
            delivery_channel="CERTIFIED_MAIL",
            rung="TERMINATION",
        ),
        COUNSEL_HEADERS,
    )


# --------------------------------------------------------------------------- #
# Instance — layer_cascade_chain_a_runs_all_four_links
# --------------------------------------------------------------------------- #
def test_one_termination_notice_drives_reseller_violations_agreement_and_stock():
    """Four levels move inside the single request that installs the top rung.

    PRD: "When the reseller's `authorization_status` becomes `TERMINATED`, the agreement
    moves `ACTIVE → TERMINATED` with `closed_reason` recorded as `SUPPLY_TERMINATED` and
    its `version` advanced, and this transition in turn recalls stock: every serialized
    unit whose `downstream_reseller_id` is this agreement's reseller and whose custody
    state is `SHIPPED_TO_RESELLER` moves to `RECALLED`, each with its own `version`
    advanced."

    Design: Corner/cross_cutting_complexity_layers/layer_cascade_chain_a_runs_all_four_links
    """
    world = _setup_acme_suspended_at_fourteen(with_spare_violation=True)
    notice = validate_success(_terminate(world), expected_status=201)
    assert notice["rung"] == "TERMINATION"

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "TERMINATED"
    assert reseller["supply_status"] == "CUT_OFF"
    assert reseller["hold_reason"] == "TERMINATION"

    spare = read_violation(world["spare_violation"]["id"])
    assert spare["status"] == "CLOSED_MOOT"
    assert spare["resolution_reason"] == "RESELLER_TERMINATED"

    agreement = read_agreement(world["agreement"]["id"])
    assert agreement["status"] == "TERMINATED"
    assert agreement["closed_reason"] == "SUPPLY_TERMINATED"

    unit = read_serial_unit(world["unit"]["id"])
    assert unit["status"] == "RECALLED"


# --------------------------------------------------------------------------- #
# Instance — layer_cascade_ordering_retains_points_of_mooted_violations
# --------------------------------------------------------------------------- #
def test_mooting_a_terminated_resellers_violations_retains_their_assessed_points():
    """Closing the open history moot does not refund anything to the ledger.

    PRD: "Every violation of that reseller whose status is `DETECTED`, `NOTICED` or
    `DISPUTED` moves to `CLOSED_MOOT` with `resolution_reason` recorded as
    `RESELLER_TERMINATED` and its own `version` advanced — and critically, the
    `assessed_points` on those violations are **retained** in the ledger, because a
    terminated reseller's history is not forgiven."

    Design: Corner/cross_cutting_complexity_layers/layer_cascade_ordering_retains_points_of_mooted_violations
    """
    world = _setup_acme_suspended_at_fourteen()
    notice = validate_success(_terminate(world), expected_status=201)
    assert notice["cumulative_points_at_issue"] == 19

    reseller = assert_reseller_points_reconcile(
        api_client, world["reseller"]["id"], BCM_HEADERS
    )
    assert reseller["violation_points_total"] == 19

    first = read_violation(world["first_violation"]["id"])
    assert first["status"] == "CLOSED_MOOT"
    assert first["assessed_points"] == 3
    assert read_violation(world["second_violation"]["id"])["assessed_points"] == 11
    assert read_violation(world["third_violation"]["id"])["assessed_points"] == 5

    # The termination cascade reaches violations, the agreement and the units; the
    # notices already served are left exactly as they were.
    assert read_notice(world["first_notice"]["id"])["status"] == "ISSUED"
    assert read_notice(world["second_notice"]["id"])["status"] == "ISSUED"


# --------------------------------------------------------------------------- #
# Instance — layer_cascade_partial_failure_writes_nothing_rejected
# --------------------------------------------------------------------------- #
def test_a_manager_attempting_termination_is_rejected_and_no_link_of_the_chain_moves():
    """The four-eyes rule stops the request before any of the four levels is written.

    PRD: "A notice whose computed `rung` is `TERMINATION` may only be issued by a
    `BrandLegalCounsel`; an attempt by a `BrandChannelManager` — who is otherwise a
    legitimate issuer of warnings and suspensions — is rejected with
    `ERR_TERMINATION_REQUIRES_COUNSEL`."

    Design: Corner/cross_cutting_complexity_layers/layer_cascade_partial_failure_writes_nothing_rejected
    """
    world = _setup_acme_suspended_at_fourteen()
    reseller_id = world["reseller"]["id"]

    validate_error(
        api_client.issue_notice(
            notice_payload(
                reseller_id,
                world["third_violation"]["id"],
                current_reseller_version(reseller_id),
                delivery_channel="CERTIFIED_MAIL",
                rung="TERMINATION",
            ),
            BCM_HEADERS,
        ),
        "ERR_TERMINATION_REQUIRES_COUNSEL",
    )

    reseller = read_reseller(reseller_id)
    assert reseller["authorization_status"] == "SUSPENDED"
    assert reseller["violation_points_total"] == 14
    assert read_agreement(world["agreement"]["id"])["status"] == "ACTIVE"
    assert read_serial_unit(world["unit"]["id"])["status"] == "SHIPPED_TO_RESELLER"
    assert read_violation(world["third_violation"]["id"])["status"] == "DETECTED"


# --------------------------------------------------------------------------- #
# Instance — layer_occ_notice_issue_with_stale_reseller_version_rejected
# --------------------------------------------------------------------------- #
def test_a_notice_carrying_a_one_behind_reseller_version_is_rejected_at_412():
    """The issuer must prove it read the ledger the rung is derived from.

    PRD: "Issuing an enforcement notice requires a non-optional
    `expected_reseller_version` field carrying the client's last observed `version` of
    the target `Reseller` row. If that value does not equal the reseller's current
    `version`, the request is rejected with `ERR_STALE_RESELLER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/layer_occ_notice_issue_with_stale_reseller_version_rejected
    """
    world = _setup_authorized_marketplace_seller()
    reseller_id = world["reseller"]["id"]
    violation, _observation, _evaluation = create_detected_violation(
        world["product"]["id"],
        reseller_id,
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        listing_url="https://marketplace.example/occ-1",
    )
    stale_version = current_reseller_version(reseller_id) - 1

    validate_error(
        api_client.issue_notice(
            notice_payload(reseller_id, violation["id"], stale_version), BCM_HEADERS
        ),
        "ERR_STALE_RESELLER_VERSION",
    )

    rows, meta = validate_paginated(
        api_client.list_notices(BCM_HEADERS, params={"reseller_id": reseller_id})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert read_violation(violation["id"])["status"] == "DETECTED"
    assert read_reseller(reseller_id)["violation_points_total"] == 0


# --------------------------------------------------------------------------- #
# Shared spine — a confirmed unauthorized trace back to the shipping distributor
# --------------------------------------------------------------------------- #
def _setup_confirmed_trace_to_northwind():
    """A traced unit whose test purchase is CONFIRMED_UNAUTHORIZED.

    The distributor's version is captured at creation, before the serial-unit
    registration mutates the row.
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(policy["id"])
    distributor = create_distributor(
        legal_name="Northwind Distribution Diversion", annual_chargeback_cap_cents=500000
    )
    version_at_creation = distributor["version"]
    unit = create_serial_unit(
        product["id"], distributor["id"], serial_number="SN-0001", lot_code="LOT-A"
    )

    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"],
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        seller_display_name="GreyBox Deals",
        listing_url="https://marketplace.example/greybox-9",
    )
    purchase = order_test_purchase(
        observation["id"], ordered_at=OBSERVED_AUG_19, purchase_price_cents=9000
    )
    capture_purchase_serial(purchase["id"], unit["serial_number"])
    purchase = confirm_unauthorized(purchase["id"])
    return {
        "product": product,
        "distributor": distributor,
        "unit": unit,
        "observation": observation,
        "purchase": purchase,
        "version_at_creation": version_at_creation,
    }


# --------------------------------------------------------------------------- #
# Instance — layer_occ_chargeback_create_with_stale_distributor_version_rejected
# --------------------------------------------------------------------------- #
def test_a_chargeback_carrying_a_stale_distributor_version_is_rejected_at_412():
    """The tier rate is read off the distributor, so the client must prove it is current.

    PRD: "Assessing a distributor chargeback requires a non-optional
    `expected_distributor_version` field carrying the client's last observed `version` of
    the target `Distributor` row. If that value does not equal the distributor's current
    `version`, the request is rejected with `ERR_STALE_DISTRIBUTOR_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/layer_occ_chargeback_create_with_stale_distributor_version_rejected
    """
    world = _setup_confirmed_trace_to_northwind()
    distributor_id = world["distributor"]["id"]
    stale_version = world["version_at_creation"]
    assert current_distributor_version(distributor_id) > stale_version

    validate_error(
        api_client.assess_chargeback(
            chargeback_payload(
                distributor_id, world["purchase"]["id"], stale_version, diverted_units=4
            ),
            BCM_HEADERS,
        ),
        "ERR_STALE_DISTRIBUTOR_VERSION",
    )

    rows, meta = validate_paginated(
        api_client.list_chargebacks(BCM_HEADERS, params={"distributor_id": distributor_id})
    )
    assert meta["total_count"] == 0
    assert rows == []
    distributor = read_distributor(distributor_id)
    assert distributor["chargeback_balance_cents"] == 0
    assert distributor["diversion_score"] == 0


# --------------------------------------------------------------------------- #
# Instance — layer_occ_correct_version_succeeds_and_bumps_the_parent
# --------------------------------------------------------------------------- #
def test_a_freshly_read_distributor_version_is_accepted_and_then_advanced():
    """The accepted token is consumed: the parent's version moves past it.

    PRD: "The distributor's `version` is advanced once for the whole assessment, and where
    the re-derivation moved the standing into `PROBATION` or `SUSPENDED`, every reseller
    whose `sourcing_distributor_id` names this distributor has its `review_required` flag
    recomputed and its `version` advanced where the value changed."

    Design: Corner/cross_cutting_complexity_layers/layer_occ_correct_version_succeeds_and_bumps_the_parent
    """
    world = _setup_confirmed_trace_to_northwind()
    distributor_id = world["distributor"]["id"]
    current_version = current_distributor_version(distributor_id)

    chargeback = validate_success(
        api_client.assess_chargeback(
            chargeback_payload(
                distributor_id, world["purchase"]["id"], current_version, diverted_units=4
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )
    assert chargeback["status"] == "ASSESSED"
    assert chargeback["tier_rate_cents_per_unit"] == tier_rate_for_score(0) == 2500
    assert chargeback["amount_cents"] == tier_rate_for_score(0) * 4 == 10000
    assert chargeback["score_delta_applied"] == score_delta(4) == 10.0

    distributor = read_distributor(distributor_id)
    assert distributor["chargeback_balance_cents"] == 10000
    assert distributor["version"] == current_version + 1


def test_replaying_the_accepted_chargeback_token_is_now_stale():
    """The same token cannot be spent twice, because the write advanced the parent.

    PRD: "Assessing a distributor chargeback requires a non-optional
    `expected_distributor_version` field carrying the client's last observed `version` of
    the target `Distributor` row. If that value does not equal the distributor's current
    `version`, the request is rejected with `ERR_STALE_DISTRIBUTOR_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/layer_occ_correct_version_succeeds_and_bumps_the_parent
    """
    world = _setup_confirmed_trace_to_northwind()
    distributor_id = world["distributor"]["id"]
    current_version = current_distributor_version(distributor_id)
    payload = chargeback_payload(
        distributor_id, world["purchase"]["id"], current_version, diverted_units=4
    )
    validate_success(api_client.assess_chargeback(payload, BCM_HEADERS), expected_status=201)

    validate_error(
        api_client.assess_chargeback(payload, BCM_HEADERS), "ERR_STALE_DISTRIBUTOR_VERSION"
    )
    assert read_distributor(distributor_id)["chargeback_balance_cents"] == 10000


# --------------------------------------------------------------------------- #
# Instance — layer_occ_reseller_version_increments_on_every_write
# --------------------------------------------------------------------------- #
def _setup_reseller_walked_to_authorized():
    """Take a fresh reseller from APPLIED to AUTHORIZED, recording each version."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(policy["id"])
    reseller = create_reseller()
    version_at_creation = reseller["version"]
    agreement = create_countersigned_agreement(reseller["id"], policy["id"])
    version_after_countersignature = current_reseller_version(reseller["id"])
    activated = validate_success(api_client.activate_agreement(agreement["id"], BCM_HEADERS))
    return {
        "policy": policy,
        "product": product,
        "reseller": reseller,
        "agreement": activated,
        "version_at_creation": version_at_creation,
        "version_after_countersignature": version_after_countersignature,
    }


def test_sending_and_activating_each_advance_the_reseller_version_by_one():
    """The token read at application is two behind by the time supply opens.

    PRD: "`version` is an integer that starts at 1 when the row is created and increases
    by exactly 1 on every mutation of that row."

    Design: Corner/cross_cutting_complexity_layers/layer_occ_reseller_version_increments_on_every_write
    """
    world = _setup_reseller_walked_to_authorized()
    assert world["version_at_creation"] == 1
    assert world["version_after_countersignature"] == 2

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["version"] == 3
    assert reseller["authorization_status"] == "AUTHORIZED"
    assert reseller["supply_status"] == "OPEN"
    assert reseller["hold_reason"] == "NONE"


def test_the_version_read_at_application_no_longer_buys_a_notice():
    """Two intervening reseller writes invalidate the token the client held.

    PRD: "Any earlier notice, any rescission, any sweep-driven reinstatement and any
    exception-driven point reversal advances the reseller's `version` and therefore
    invalidates a view read before it."

    Design: Corner/cross_cutting_complexity_layers/layer_occ_reseller_version_increments_on_every_write
    """
    world = _setup_reseller_walked_to_authorized()
    reseller_id = world["reseller"]["id"]
    pin_clock(CLOCK_AUG_20)
    violation, _observation, _evaluation = create_detected_violation(
        world["product"]["id"],
        reseller_id,
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        listing_url="https://marketplace.example/occ-walk",
    )

    validate_error(
        api_client.issue_notice(
            notice_payload(reseller_id, violation["id"], world["version_at_creation"]),
            BCM_HEADERS,
        ),
        "ERR_STALE_RESELLER_VERSION",
    )
    assert read_violation(violation["id"])["status"] == "DETECTED"
