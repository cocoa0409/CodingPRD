"""The derived-aggregate layer of the same stacked requests, continued.

Two running totals are maintained on rows a client reads directly — the reseller's
points ledger and the product's open-exception count — and each must equal the figure
recomputed from its contributors after a create, an update, a reversal and an expiry.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import ADMIN_HEADERS, BCM_HEADERS, api_client
from test_helpers.assertions import (
    assert_open_exception_count_reconciles,
    assert_reseller_points_reconcile,
    violation_points,
)
from test_helpers.constants import EVIDENCE_HASH_2
from test_helpers.factories import (
    notice_payload,
    violation_dispute_decision_payload,
    violation_dispute_payload,
)
from test_helpers.fixtures import (
    approve_exception,
    create_authorized_reseller,
    create_detected_violation,
    create_product,
    create_published_policy,
    current_reseller_version,
    issue_notice,
    pin_clock,
    read_effective_floor,
    read_exception,
    read_notice,
    read_product,
    read_reseller,
    read_violation,
    request_exception,
    run_sweep,
)
from test_helpers.test_users import make_reseller_headers

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
CLOCK_AUG_25 = "2026-08-25T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
SUSPENSION_STARTS = "2026-09-01T00:00:00Z"
SUSPENSION_ENDS = "2026-09-10T00:00:00Z"
STANDARD_FLOOR = 15000


def _setup_authorized_marketplace_seller():
    """A published policy, a 15000-floor product and one AUTHORIZED marketplace seller."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(policy["id"])
    reseller, agreement = create_authorized_reseller(policy["id"])
    pin_clock(CLOCK_AUG_20)
    return {"policy": policy, "product": product, "reseller": reseller, "agreement": agreement}


# --------------------------------------------------------------------------- #
# Instance — layer_derived_points_total_after_first_notice
# --------------------------------------------------------------------------- #
def test_the_points_ledger_stays_at_zero_until_the_first_notice_charges_it():
    """A merely detected violation has no assessed points and contributes nothing.

    PRD: "A reseller's `violation_points_total` equals the sum of `assessed_points` over
    that reseller's violations whose `assessed_points` is not null and whose `status` is
    one of `NOTICED`, `DISPUTED`, `CURED`, `ESCALATED` or `CLOSED_MOOT`. A violation that
    was detected but never noticed contributes nothing, because its `assessed_points` is
    still null; a `VOIDED` violation contributes nothing, because voiding clears
    `assessed_points` back to null."

    Design: Corner/cross_cutting_complexity_layers/layer_derived_points_total_after_first_notice
    """
    world = _setup_authorized_marketplace_seller()
    reseller_id = world["reseller"]["id"]
    violation, _observation, _evaluation = create_detected_violation(
        world["product"]["id"],
        reseller_id,
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        listing_url="https://marketplace.example/derived-1",
    )
    assert read_reseller(reseller_id)["violation_points_total"] == 0
    assert violation["assessed_points"] is None

    notice = validate_success(
        api_client.issue_notice(
            notice_payload(reseller_id, violation["id"], current_reseller_version(reseller_id)),
            BCM_HEADERS,
        ),
        expected_status=201,
    )
    assert notice["cumulative_points_at_issue"] == 3

    reseller = assert_reseller_points_reconcile(api_client, reseller_id, BCM_HEADERS)
    assert reseller["violation_points_total"] == 3
    assert read_violation(violation["id"])["assessed_points"] == 3


# --------------------------------------------------------------------------- #
# Shared spine — a warning of three points followed by a suspension of eleven
# --------------------------------------------------------------------------- #
def _setup_ledger_at_fourteen():
    """Two noticed marketplace breaches: 3 points, then 11 more on the repeat weight."""
    world = _setup_authorized_marketplace_seller()
    reseller_id = world["reseller"]["id"]
    first_violation, _o1, _e1 = create_detected_violation(
        world["product"]["id"],
        reseller_id,
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        listing_url="https://marketplace.example/derived-ledger-1",
    )
    first_notice = issue_notice(reseller_id, first_violation["id"])
    second_violation, _o2, _e2 = create_detected_violation(
        world["product"]["id"],
        reseller_id,
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_2,
        listing_url="https://marketplace.example/derived-ledger-2",
    )
    second_notice = issue_notice(
        reseller_id,
        second_violation["id"],
        suspension_starts_at=SUSPENSION_STARTS,
        suspension_ends_at=SUSPENSION_ENDS,
    )
    world.update(
        {
            "first_violation": first_violation,
            "first_notice": first_notice,
            "second_violation": second_violation,
            "second_notice": second_notice,
        }
    )
    return world


# --------------------------------------------------------------------------- #
# Instance — layer_derived_points_total_after_second_notice
# --------------------------------------------------------------------------- #
def test_the_second_notice_adds_to_the_aggregate_without_disturbing_the_first():
    """Eleven more points take the ledger from three to fourteen.

    PRD: "The reseller's `violation_points_total` is increased by the assessed points and
    the reseller's `version` is advanced."

    Design: Corner/cross_cutting_complexity_layers/layer_derived_points_total_after_second_notice
    """
    world = _setup_ledger_at_fourteen()
    assert world["first_notice"]["assessed_points"] == 3
    assert world["second_notice"]["assessed_points"] == violation_points(
        STANDARD_FLOOR, 9000, "MARKETPLACE", 1
    ) == 11
    assert world["second_notice"]["cumulative_points_at_issue"] == 14

    reseller = assert_reseller_points_reconcile(
        api_client, world["reseller"]["id"], BCM_HEADERS
    )
    assert reseller["violation_points_total"] == 14
    assert read_violation(world["first_violation"]["id"])["assessed_points"] == 3
    assert read_violation(world["second_violation"]["id"])["assessed_points"] == 11


# --------------------------------------------------------------------------- #
# Instance — layer_derived_points_total_after_source_violation_is_voided
# --------------------------------------------------------------------------- #
def test_sustaining_a_dispute_removes_its_contributor_from_the_aggregate():
    """Voiding the source violation reconciles the ledger down to eleven.

    PRD: "A `decision` of `SUSTAIN` moves it `DISPUTED → VOIDED`: `resolution_reason` is
    set to `DISPUTE_SUSTAINED`; the `assessed_points` are subtracted from the reseller's
    `violation_points_total` and then `assessed_points`, `assessed_floor_cents` and
    `cure_deadline_at` are all cleared to null with the reseller's `version` advanced; the
    latest non-rescinded notice for that violation moves to `RESCINDED`, which — when that
    notice's `rung` was `SUSPENSION` — reinstates the reseller as described below; and the
    violation's `version` is advanced."

    Design: Corner/cross_cutting_complexity_layers/layer_derived_points_total_after_source_violation_is_voided
    """
    world = _setup_ledger_at_fourteen()
    reseller_id = world["reseller"]["id"]
    first_violation_id = world["first_violation"]["id"]
    validate_success(
        api_client.dispute_violation(
            first_violation_id,
            violation_dispute_payload(
                dispute_reason="Listing was a third-party clone of our storefront."
            ),
            make_reseller_headers(reseller_id),
        )
    )

    decided = validate_success(
        api_client.decide_violation_dispute(
            first_violation_id,
            violation_dispute_decision_payload(
                "SUSTAIN", decision_reason="First listing was misattributed."
            ),
            BCM_HEADERS,
        )
    )
    assert decided["status"] == "VOIDED"
    assert decided["assessed_points"] is None

    reseller = assert_reseller_points_reconcile(api_client, reseller_id, BCM_HEADERS)
    assert reseller["violation_points_total"] == 11
    assert read_notice(world["first_notice"]["id"])["status"] == "RESCINDED"
    assert read_notice(world["second_notice"]["id"])["status"] == "ISSUED"


# --------------------------------------------------------------------------- #
# Instance — layer_derived_open_exception_count_after_expiry
# --------------------------------------------------------------------------- #
def test_open_exception_count_climbs_on_approval_and_falls_when_the_sweep_expires_it():
    """The product's running count tracks its APPROVED exceptions in both directions.

    PRD: "A product's `open_exception_count` equals the count of that product's pricing
    exceptions in status `APPROVED`. Exceptions in `REQUESTED`, `REJECTED`, `EXPIRED` or
    `VOIDED` are excluded, and the count is recomputed on every approval, expiry and
    voiding."

    Design: Corner/cross_cutting_complexity_layers/layer_derived_open_exception_count_after_expiry
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(policy["id"])
    assert product["open_exception_count"] == 0

    exception = request_exception(
        product["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at="2026-08-10T00:00:00Z",
        ends_at=CLOCK_AUG_25,
        channel_scope="ALL",
        requested_override_floor_cents=13000,
        dealer_input_source="BRAND_MARKETING_PLAN",
    )
    approved = approve_exception(exception["id"])
    assert approved["status"] == "APPROVED"
    assert approved["override_floor_cents"] == 13000
    assert read_product(product["id"])["open_exception_count"] == 1

    pin_clock(CLOCK_AUG_25)
    sweep = run_sweep(ADMIN_HEADERS)
    assert sweep["expired_exceptions"] == 1

    assert read_exception(exception["id"])["status"] == "EXPIRED"
    product = assert_open_exception_count_reconciles(api_client, product["id"], BCM_HEADERS)
    assert product["open_exception_count"] == 0

    floor = read_effective_floor(product["id"], channel="MARKETPLACE")
    assert floor["effective_map_floor_cents"] == STANDARD_FLOOR
    assert floor["floor_source"] == "STANDARD"
    assert floor["applied_exception_id"] is None
