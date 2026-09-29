"""Every write in this system settles before it answers.

A computation endpoint returns the figures it just stored, an enforcement write returns
a ladder snapshot that the reseller's own reconciliation read already agrees with, and a
four-level cascade is complete by the time the response is written — so a client that
re-reads any of the touched rows immediately afterwards sees the same values, with no
settling period to wait out.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import ANALYST_HEADERS, BCM_HEADERS, COUNSEL_HEADERS, api_client
from test_helpers.assertions import (
    deviation_cents,
    deviation_pct,
    violation_points,
)
from test_helpers.constants import EVIDENCE_HASH_2, EVIDENCE_HASH_3
from test_helpers.factories import notice_payload
from test_helpers.fixtures import (
    capture_observation,
    create_authorized_reseller,
    create_detected_violation,
    create_distributor,
    create_product,
    create_published_policy,
    create_serial_unit,
    current_reseller_version,
    issue_notice,
    pin_clock,
    read_agreement,
    read_compliance_summary,
    read_observation,
    read_reseller,
    read_violation,
    ship_unit_downstream,
)
from test_helpers.test_users import make_distributor_headers

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
OBSERVED_AUG_19 = "2026-08-19T00:00:00Z"
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


def _setup_captured_marketplace_breach():
    """An AUTHORIZED marketplace reseller with one 14000-cent listing still CAPTURED."""
    world = _setup_authorized_marketplace_seller()
    product = world["product"]
    reseller = world["reseller"]
    observation = capture_observation(
        product["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        matched_reseller_id=reseller["id"],
        listing_url="https://marketplace.example/immediate-1",
    )
    world["observation"] = observation
    return world


# --------------------------------------------------------------------------- #
# Instance — consistency_evaluate_returns_every_derived_field_immediately
# --------------------------------------------------------------------------- #
def test_the_evaluation_response_carries_every_derived_figure_it_computed():
    """Floor, effective price, deviation and the opened violation come back at once.

    PRD: "When the effective advertised price is strictly less than the resolved floor,
    the observation moves `CAPTURED → EVALUATED_BREACH`. It stores the same computed
    fields plus a genuine `deviation_cents` and `deviation_pct`, and advances its own
    `version`."

    Design: Corner/consistency_model/consistency_evaluate_returns_every_derived_field_immediately
    """
    world = _setup_captured_marketplace_breach()
    evaluation = validate_success(
        api_client.evaluate_observation(world["observation"]["id"], ANALYST_HEADERS)
    )

    assert evaluation["evaluation_status"] == "EVALUATED_BREACH"
    assert evaluation["effective_advertised_price_cents"] == 14000
    assert evaluation["effective_map_floor_cents"] == STANDARD_FLOOR
    assert evaluation["floor_source"] == "STANDARD"
    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 14000) == 1000
    assert evaluation["deviation_pct"] == deviation_pct(STANDARD_FLOOR, 1000) == 0.0667
    assert evaluation["cited_policy_id"] == world["policy"]["id"]
    assert evaluation["provisional_points"] == violation_points(
        STANDARD_FLOOR, 14000, "MARKETPLACE", 0
    ) == 3
    assert evaluation["violation_id"] is not None


def test_re_reading_the_observation_and_its_violation_returns_the_same_figures():
    """The follow-up reads need no settling period to catch up with the write.

    PRD: "If `matched_reseller_id` is not null, a violation row is opened in status
    `DETECTED` carrying `provisional_floor_cents` — the floor as resolved at `observed_at`
    — and `provisional_points`, together with `observation_id` pointing back at the
    evidence, `reseller_id` copied from the observation's `matched_reseller_id`, and
    `cited_policy_id` set to the policy the selection rule picked for `observed_at`."

    Design: Corner/consistency_model/consistency_evaluate_returns_every_derived_field_immediately
    """
    world = _setup_captured_marketplace_breach()
    evaluation = validate_success(
        api_client.evaluate_observation(world["observation"]["id"], ANALYST_HEADERS)
    )

    observation = read_observation(world["observation"]["id"])
    assert observation["evaluation_status"] == evaluation["evaluation_status"]
    assert (
        observation["effective_advertised_price_cents"]
        == evaluation["effective_advertised_price_cents"]
    )
    assert observation["effective_map_floor_cents"] == evaluation["effective_map_floor_cents"]
    assert observation["deviation_cents"] == evaluation["deviation_cents"]
    assert observation["deviation_pct"] == evaluation["deviation_pct"]

    violation = read_violation(evaluation["violation_id"])
    assert violation["status"] == "DETECTED"
    assert violation["provisional_points"] == 3
    assert violation["provisional_floor_cents"] == STANDARD_FLOOR
    assert violation["reseller_id"] == world["reseller"]["id"]
    assert violation["observation_id"] == world["observation"]["id"]


# --------------------------------------------------------------------------- #
# Instance — consistency_notice_issuance_exposes_the_new_ledger_in_the_same_request
# --------------------------------------------------------------------------- #
def test_the_notice_snapshot_and_the_reconciliation_read_agree_immediately():
    """The ladder figure returned by the write is already the reseller's stored ledger.

    PRD: "It reports `reseller_id`, the stored `violation_points_total`, the
    `contributing_violation_count` of violations that qualify under the ledger definition
    of §2.11, the `summed_assessed_points` obtained by adding up those violations'
    `assessed_points` — which must equal the stored total, since that is the whole point
    of the read — the `highest_issued_rung` served so far (reported as the empty-history
    case when no non-rescinded notice exists), the `next_rung` the ladder would install
    on the next notice, and the two gaps `points_to_suspension` and
    `points_to_termination`, each being the reseller's own governing thresholds minus the
    current total, floored at zero when the threshold has already been passed."

    Design: Corner/consistency_model/consistency_notice_issuance_exposes_the_new_ledger_in_the_same_request
    """
    world = _setup_authorized_marketplace_seller()
    violation, _observation, _evaluation = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        listing_url="https://marketplace.example/immediate-ledger",
    )
    reseller_id = world["reseller"]["id"]

    notice = validate_success(
        api_client.issue_notice(
            notice_payload(reseller_id, violation["id"], current_reseller_version(reseller_id)),
            BCM_HEADERS,
        ),
        expected_status=201,
    )
    assert notice["status"] == "ISSUED"
    assert notice["assessed_points"] == 3
    assert notice["cumulative_points_at_issue"] == 3

    summary = read_compliance_summary(reseller_id)
    assert summary["violation_points_total"] == 3
    assert summary["summed_assessed_points"] == 3
    assert summary["contributing_violation_count"] == 1
    assert summary["highest_issued_rung"] == "WARNING"
    assert summary["points_to_suspension"] == 3
    assert summary["points_to_termination"] == 9
    assert read_reseller(reseller_id)["violation_points_total"] == 3


# --------------------------------------------------------------------------- #
# Instance — consistency_cascade_effects_are_visible_without_a_re_read_delay
# --------------------------------------------------------------------------- #
def _setup_terminated_acme():
    """Walk Acme up the ladder to TERMINATION with one unit in its warehouse."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(policy["id"])
    distributor = create_distributor(legal_name="Northwind Distribution Immediate")
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
        listing_url="https://marketplace.example/immediate-cascade-1",
    )
    issue_notice(reseller["id"], first_violation["id"])
    second_violation, _o2, _e2 = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_2,
        listing_url="https://marketplace.example/immediate-cascade-2",
    )
    issue_notice(
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
        evidence_hash=EVIDENCE_HASH_3,
        listing_url="https://marketplace.example/immediate-cascade-3",
    )
    notice = validate_success(
        api_client.issue_notice(
            notice_payload(
                reseller["id"],
                third_violation["id"],
                current_reseller_version(reseller["id"]),
                delivery_channel="CERTIFIED_MAIL",
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    return {
        "product": product,
        "distributor": distributor,
        "reseller": reseller,
        "agreement": agreement,
        "unit": unit,
        "notice": notice,
    }


def test_the_recalled_unit_is_already_recalled_when_the_distributor_looks():
    """Four levels down, the cascade has landed before the response is written.

    PRD: "When the reseller's `authorization_status` becomes `TERMINATED`, the agreement
    moves `ACTIVE → TERMINATED` with `closed_reason` recorded as `SUPPLY_TERMINATED` and
    its `version` advanced, and this transition in turn recalls stock: every serialized
    unit whose `downstream_reseller_id` is this agreement's reseller and whose custody
    state is `SHIPPED_TO_RESELLER` moves to `RECALLED`, each with its own `version`
    advanced."

    Design: Corner/consistency_model/consistency_cascade_effects_are_visible_without_a_re_read_delay
    """
    world = _setup_terminated_acme()
    assert world["notice"]["rung"] == "TERMINATION"

    unit = validate_success(
        api_client.get_serial_unit(
            world["unit"]["id"], make_distributor_headers(world["distributor"]["id"])
        )
    )
    assert unit["status"] == "RECALLED"
    assert unit["downstream_reseller_id"] == world["reseller"]["id"]

    agreement = read_agreement(world["agreement"]["id"])
    assert agreement["status"] == "TERMINATED"
    assert agreement["closed_reason"] == "SUPPLY_TERMINATED"

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "TERMINATED"
    assert reseller["supply_status"] == "CUT_OFF"
