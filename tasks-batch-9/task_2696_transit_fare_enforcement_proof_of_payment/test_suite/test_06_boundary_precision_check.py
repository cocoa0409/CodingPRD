"""
Inclusive and strict comparison edges: a sampling gate that must accept exactly
0.8000, an expiry comparison that must accept an instant equal to the
inspection, and a signage gate that must accept exactly 0.9000.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_DISPOSITION_NOT_SUPPORTED,
    ERR_SAMPLE_SIZE_INADEQUATE,
    ERR_SIGNAGE_BELOW_THRESHOLD,
)
from test_helpers.assertions import assert_instant_equals, assert_rate_equals
from test_helpers.constants import (
    DEPLOYMENT_STATUS_ACTIVE,
    DEPLOYMENT_STATUS_CLOSED,
    IDENTITY_SELF_REPORTED,
    MEDIA_SMARTCARD,
    OUTCOME_COMPLIANT,
    OUTCOME_PENDING,
    VALIDATION_EXPIRED,
    VALIDATION_VALID,
    ZONE_STATUS_DESIGNATED,
    ZONE_STATUS_PENDING_SIGNAGE,
)
from test_helpers.test_users import PLANNER_HEADERS, make_fare_inspector_headers


# ── The sampling gate at exactly four fifths ─────────────────────────

def _deployment_with_three_of_five_sampled(api):
    """
    An active deployment against a target of 5 carrying three resolved
    encounters and nothing pending.
    """
    env = fixtures.build_environment(api)
    deployment = fixtures.build_active_deployment(api, env)
    inspector_id = env["inspector"]["id"]

    compliant_one = fixtures.build_pending_encounter(
        api,
        env,
        deployment,
        occurred_at="2026-08-05T07:00:00Z",
        fare_media_type=MEDIA_SMARTCARD,
        media_reference="SC-0001",
        media_validated_at="2026-08-05T06:58:00Z",
        media_expires_at="2026-12-01T00:00:00Z",
        media_zone_code="ZN1",
        identity_capture_method=IDENTITY_SELF_REPORTED,
    )
    fixtures.resolve(api, compliant_one["id"], inspector_id, "COMPLIANT")
    warned = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T07:30:00Z"
    )
    fixtures.resolve(api, warned["id"], inspector_id, "WARNING_ISSUED")
    compliant_two = fixtures.build_pending_encounter(
        api,
        env,
        deployment,
        occurred_at="2026-08-05T08:00:00Z",
        fare_media_type=MEDIA_SMARTCARD,
        media_reference="SC-0002",
        media_validated_at="2026-08-05T07:58:00Z",
        media_expires_at="2026-12-01T00:00:00Z",
        media_zone_code="ZN1",
        identity_capture_method=IDENTITY_SELF_REPORTED,
    )
    fixtures.resolve(api, compliant_two["id"], inspector_id, "COMPLIANT")
    return env, deployment


def _add_fourth_warning(api, env, deployment):
    fourth = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T08:30:00Z"
    )
    fixtures.resolve(api, fourth["id"], env["inspector"]["id"], "WARNING_ISSUED")
    return fourth


def test_three_fifths_of_the_target_sample_is_refused_at_the_gate(api):
    """
    Closing requires `sample_adequacy_ratio` to be at least 0.8000, and a
    deployment standing at 0.6000 is refused with `ERR_SAMPLE_SIZE_INADEQUATE`
    while its `status` stays `ACTIVE`.

    Design: Difficulty/boundary_precision_check/sample_adequacy_ratio_exactly_at_eight_tenths_closes_the_deployment
    """
    env, deployment = _deployment_with_three_of_five_sampled(api)

    validate_error(
        api.close_deployment(deployment["id"], PLANNER_HEADERS),
        ERR_SAMPLE_SIZE_INADEQUATE,
        409,
    )

    unclosed = fixtures.read_deployment(api, deployment["id"])
    assert unclosed["status"] == DEPLOYMENT_STATUS_ACTIVE
    assert unclosed["achieved_sample_count"] == 3
    assert_rate_equals(unclosed["sample_adequacy_ratio"], 0.6000, "sample_adequacy_ratio")


def test_landing_on_exactly_four_fifths_lets_the_close_through(api):
    """
    A fourth encounter puts `sample_adequacy_ratio` at exactly 0.8000, which
    satisfies the at-least comparison, so the close succeeds and the deployment
    moves `ACTIVE` to `CLOSED`.

    Design: Difficulty/boundary_precision_check/sample_adequacy_ratio_exactly_at_eight_tenths_closes_the_deployment
    """
    env, deployment = _deployment_with_three_of_five_sampled(api)
    api.close_deployment(deployment["id"], PLANNER_HEADERS)
    _add_fourth_warning(api, env, deployment)

    at_the_edge = fixtures.read_deployment(api, deployment["id"])
    assert at_the_edge["achieved_sample_count"] == 4
    assert at_the_edge["voided_encounter_count"] == 0
    assert_rate_equals(at_the_edge["sample_adequacy_ratio"], 0.8000, "sample_adequacy_ratio")

    closed = validate_success(api.close_deployment(deployment["id"], PLANNER_HEADERS), 200)
    assert closed["status"] == DEPLOYMENT_STATUS_CLOSED


def test_the_close_at_the_edge_freezes_the_two_rates_and_the_cost(api):
    """
    Closing computes `measured_evasion_rate_bps`, `resolved_evasion_rate_bps` and
    `enforcement_cost_cents`, and with two of the four sampled riders
    non-compliant both rates read 5000.

    Design: Difficulty/boundary_precision_check/sample_adequacy_ratio_exactly_at_eight_tenths_closes_the_deployment
    """
    env, deployment = _deployment_with_three_of_five_sampled(api)
    _add_fourth_warning(api, env, deployment)
    fixtures.get_success_data(api.close_deployment(deployment["id"], PLANNER_HEADERS))

    closed = fixtures.read_deployment(api, deployment["id"])
    assert closed["measured_evasion_rate_bps"] == 5000
    assert closed["resolved_evasion_rate_bps"] == 5000
    assert closed["enforcement_cost_cents"] == 136080
    assert fixtures.read_rider(api, env["rider"]["id"])["prior_warning_count"] == 2


# ── The expiry comparison at the inspection instant ──────────────────

EDGE_OCCURRED_AT = "2026-08-05T07:00:00Z"


def _two_encounters_either_side_of_the_expiry_edge(api):
    """
    Two smartcard encounters inspected at the same instant: one whose media
    expires exactly then, one whose media expired a minute earlier.
    """
    env = fixtures.build_environment(api)
    second_rider = fixtures.register_rider(
        api,
        rider_ref="R-200",
        display_name="Rider Two",
        demographic_band="BAND_B",
        residence_geo_tract="T-002",
    )
    deployment = fixtures.build_active_deployment(api, env)

    on_the_edge = fixtures.build_pending_encounter(
        api,
        env,
        deployment,
        occurred_at=EDGE_OCCURRED_AT,
        fare_media_type=MEDIA_SMARTCARD,
        media_reference="SC-EDGE-1",
        media_validated_at="2026-08-05T06:50:00Z",
        media_expires_at=EDGE_OCCURRED_AT,
        media_zone_code="ZN1",
        identity_capture_method=IDENTITY_SELF_REPORTED,
    )
    a_minute_late = fixtures.build_pending_encounter(
        api,
        env,
        deployment,
        occurred_at=EDGE_OCCURRED_AT,
        fare_media_type=MEDIA_SMARTCARD,
        rider=second_rider,
        media_reference="SC-EDGE-2",
        media_validated_at="2026-08-05T06:50:00Z",
        media_expires_at="2026-08-05T06:59:00Z",
        media_zone_code="ZN1",
        identity_capture_method=IDENTITY_SELF_REPORTED,
    )
    return env, deployment, on_the_edge, a_minute_late


def test_media_expiring_at_the_inspection_instant_is_not_yet_expired(api):
    """
    Media counts as expired only where `media_expires_at` is strictly before
    `occurred_at`, so an expiry equal to the inspection instant yields a
    `validation_result` of `VALID` while one minute earlier yields `EXPIRED`.

    Design: Difficulty/boundary_precision_check/media_expiry_equal_to_occurred_at_is_valid_one_minute_earlier_is_expired
    """
    _env, _deployment, on_the_edge, a_minute_late = (
        _two_encounters_either_side_of_the_expiry_edge(api)
    )

    assert on_the_edge["validation_result"] == VALIDATION_VALID
    assert a_minute_late["validation_result"] == VALIDATION_EXPIRED


def test_only_the_valid_side_of_the_edge_accepts_a_compliant_disposition(api):
    """
    A `COMPLIANT` disposition is admissible only where `validation_result` is
    `VALID`; against the expired encounter it is refused with
    `ERR_DISPOSITION_NOT_SUPPORTED` and that encounter stays `PENDING`.

    Design: Difficulty/boundary_precision_check/media_expiry_equal_to_occurred_at_is_valid_one_minute_earlier_is_expired
    """
    env, deployment, on_the_edge, a_minute_late = (
        _two_encounters_either_side_of_the_expiry_edge(api)
    )
    inspector_headers = make_fare_inspector_headers(env["inspector"]["id"])

    resolved = validate_success(
        api.resolve_encounter(
            on_the_edge["id"], factories.resolve_payload("COMPLIANT"), inspector_headers
        ),
        200,
    )
    assert resolved["outcome"] == OUTCOME_COMPLIANT

    validate_error(
        api.resolve_encounter(
            a_minute_late["id"], factories.resolve_payload("COMPLIANT"), inspector_headers
        ),
        ERR_DISPOSITION_NOT_SUPPORTED,
        409,
    )
    assert fixtures.read_encounter(api, a_minute_late["id"])["outcome"] == OUTCOME_PENDING

    counted = fixtures.read_deployment(api, deployment["id"])
    assert counted["achieved_sample_count"] == 2
    assert_rate_equals(counted["sample_adequacy_ratio"], 0.4000, "sample_adequacy_ratio")


# ── The signage gate at exactly nine tenths ──────────────────────────

def _zone_awaiting_signage_with_a_deficient_audit(api):
    """A zone in PENDING_SIGNAGE whose only audit found 8 of its 10 signs."""
    env = fixtures.build_environment(api, designate=False)
    zone_id = env["zone"]["id"]
    fixtures.get_success_data(api.submit_zone_for_signage(zone_id, PLANNER_HEADERS))
    fixtures.file_audit(
        api,
        zone_id,
        signs_verified_count=8,
        audited_at="2026-08-01T01:00:00Z",
        deficiency_note="Two shelter signs still missing.",
    )
    fixtures.move_clock(api, "2026-08-01T02:00:00Z")
    return zone_id


def test_eight_of_ten_signs_is_below_the_gate(api):
    """
    Designation requires `signage_compliance_pct` to be at least 0.9000, so a
    zone standing at 0.8000 is refused with `ERR_SIGNAGE_BELOW_THRESHOLD` and
    stays in `PENDING_SIGNAGE`.

    Design: Difficulty/boundary_precision_check/signage_compliance_exactly_nine_tenths_permits_designation
    """
    zone_id = _zone_awaiting_signage_with_a_deficient_audit(api)

    deficient = fixtures.read_zone(api, zone_id)
    assert_rate_equals(deficient["signage_compliance_pct"], 0.8000, "signage_compliance_pct")

    validate_error(
        api.designate_zone(zone_id, PLANNER_HEADERS), ERR_SIGNAGE_BELOW_THRESHOLD, 409
    )
    assert (
        fixtures.read_zone(api, zone_id)["designation_status"] == ZONE_STATUS_PENDING_SIGNAGE
    )


def test_the_later_audit_supersedes_rather_than_averages(api):
    """
    The compliance figure is derived from the zone's latest audit by `audited_at`,
    so a following 9-of-10 audit lands the zone on exactly 0.9000 rather than the
    0.8500 an average of the two would give, and the gate opens.

    Design: Difficulty/boundary_precision_check/signage_compliance_exactly_nine_tenths_permits_designation
    """
    zone_id = _zone_awaiting_signage_with_a_deficient_audit(api)
    api.designate_zone(zone_id, PLANNER_HEADERS)

    fixtures.file_audit(
        api,
        zone_id,
        signs_verified_count=9,
        audited_at="2026-08-01T03:00:00Z",
        deficiency_note="One shelter sign remains outstanding.",
    )
    fixtures.move_clock(api, "2026-08-01T04:00:00Z")

    at_the_edge = fixtures.read_zone(api, zone_id)
    assert at_the_edge["verified_sign_count"] == 9
    assert_rate_equals(at_the_edge["signage_compliance_pct"], 0.9000, "signage_compliance_pct")

    designated = validate_success(api.designate_zone(zone_id, PLANNER_HEADERS), 200)
    assert designated["designation_status"] == ZONE_STATUS_DESIGNATED
    assert_instant_equals(designated["designated_at"], "2026-08-01T04:00:00Z", "designated.designated_at")


def test_the_superseded_audit_stays_in_the_append_only_trail(api):
    """
    Signage audits are an append-only trail, so the deficient audit is still
    listed beside the one that superseded it.

    Design: Difficulty/boundary_precision_check/signage_compliance_exactly_nine_tenths_permits_designation
    """
    zone_id = _zone_awaiting_signage_with_a_deficient_audit(api)
    fixtures.file_audit(
        api,
        zone_id,
        signs_verified_count=9,
        audited_at="2026-08-01T03:00:00Z",
        deficiency_note="One shelter sign remains outstanding.",
    )

    rows, meta = validate_paginated(api.list_zone_signage_audits(zone_id, PLANNER_HEADERS))
    assert meta["total_count"] == 2
    assert [row["signs_verified_count"] for row in rows] == [8, 9]
