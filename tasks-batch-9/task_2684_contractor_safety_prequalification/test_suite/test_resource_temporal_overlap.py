"""Difficulty rule: resource_temporal_overlap.

Two interval regimes that must not be confused: a certificate's half-open
coverage interval, which admits a touching renewal, and a badge's closed access
window, which collides at a shared endpoint.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (  # noqa: E402
    ERR_ACCESS_COOLDOWN_ACTIVE,
    ERR_ACCESS_WINDOW_OVERLAP,
    ERR_COVERAGE_PERIOD_OVERLAP,
)
from test_helpers.assertions import (  # noqa: E402
    assert_certificate_state,
    assert_grant_state,
    assert_instant_equals,
    assert_site_posture,
)
from test_helpers.constants import ALTERNATE_CARRIER, INITIAL_CLOCK  # noqa: E402
from test_helpers.factories import certificate_payload, grant_payload  # noqa: E402


def _insured_through_july_2027(build):
    """A contractor with GL and WC both running 2026-07-01 to 2027-07-01."""
    build.set_clock(INITIAL_CLOCK)
    contractor = build.create_contractor()
    certificates = build.insure(contractor["id"], ("GL", "WC"))
    return contractor, certificates


def test_renewal_starting_exactly_at_the_incumbent_expiration_is_accepted(build, api):
    """The half-open interval lets a seamless renewal in.

    PRD Section 3.5: "Because the interval excludes its endpoint, a renewal whose
    `effective_date` is exactly the incumbent's `expiration_date` does not
    intersect and is accepted, while a renewal starting one second earlier does
    intersect and is refused."

    Design: Difficulty/resource_temporal_overlap/certificate_half_open_interval_admits_touching_renewal_but_rejects_a_one_second_overlap
    """
    contractor, certificates = _insured_through_july_2027(build)
    headers = build.contractor_headers(contractor["id"])

    renewal = validate_success(
        api.create_certificate(
            contractor["id"],
            certificate_payload(
                "GL",
                carrier_name=ALTERNATE_CARRIER,
                each_occurrence_limit=1000000,
                aggregate_limit=2000000,
                effective_date="2027-07-01T00:00:00Z",
                expiration_date="2028-07-01T00:00:00Z",
            ),
            headers,
        ),
        201,
    )
    assert_certificate_state(
        renewal,
        verification_status="PENDING",
        lifecycle_status="NOT_YET_EFFECTIVE",
    )
    assert renewal["carrier_name"] == ALTERNATE_CARRIER

    # The incumbent is untouched by the renewal filing.
    rows, _meta = validate_paginated(
        api.list_certificates(contractor["id"], headers, {"coverage_type": "GL"})
    )
    live = [row for row in rows if row["id"] == certificates["GL"]["id"]]
    assert len(live) == 1
    assert_certificate_state(
        live[0], verification_status="VERIFIED", lifecycle_status="CURRENT"
    )


def test_renewal_starting_one_second_early_intersects_and_is_refused(build, api):
    """One second of shared coverage is an intersection.

    PRD Section 3.5: "No new certificate may be filed whose interval intersects
    the interval of an existing certificate for the same contractor and the same
    coverage type while that existing certificate holds a `verification_status`
    of `PENDING` or `VERIFIED`; an intersection is `ERR_COVERAGE_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/certificate_half_open_interval_admits_touching_renewal_but_rejects_a_one_second_overlap
    """
    contractor, _certificates = _insured_through_july_2027(build)
    headers = build.contractor_headers(contractor["id"])

    validate_success(
        api.create_certificate(
            contractor["id"],
            certificate_payload(
                "GL",
                carrier_name=ALTERNATE_CARRIER,
                effective_date="2027-07-01T00:00:00Z",
                expiration_date="2028-07-01T00:00:00Z",
            ),
            headers,
        ),
        201,
    )

    response = api.create_certificate(
        contractor["id"],
        certificate_payload(
            "GL",
            carrier_name=ALTERNATE_CARRIER,
            effective_date="2027-06-30T23:59:59Z",
            expiration_date="2028-06-30T23:59:59Z",
        ),
        headers,
    )
    validate_error(response, ERR_COVERAGE_PERIOD_OVERLAP, 409)

    rows, meta = validate_paginated(
        api.list_certificates(contractor["id"], headers, {"coverage_type": "GL"})
    )
    assert meta["total_count"] == 2, (
        f"expected exactly two GL rows after the refusal, got {meta['total_count']}"
    )
    assert len(rows) == 2


def _badged_worker(build):
    """The canonical approval with one live badge expiring 2026-09-01."""
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()
    grant = build.grant_badge(
        scenario["worker_id"],
        scenario["site_id"],
        scenario["prequalification_id"],
        scenario["contractor_id"],
        expires_at="2026-09-01T00:00:00Z",
    )
    scenario["grant"] = grant
    return scenario


def test_second_window_overlapping_a_live_badge_is_refused(build, api):
    """Closed access windows collide on any shared instant.

    PRD Section 3.8: "If the requested window shares even a single instant with
    the window of any grant for the same worker and the same site that is still
    in `GRANTED`, the request is refused with `ERR_ACCESS_WINDOW_OVERLAP` —
    touching endpoints do collide here, unlike the half-open coverage rule."

    Design: Difficulty/resource_temporal_overlap/access_window_closed_interval_intersects_at_touching_endpoints_while_cooldown_clears_exactly_at_24h
    """
    scenario = _badged_worker(build)
    assert_grant_state(scenario["grant"], status="GRANTED")
    assert_instant_equals(scenario["grant"]["granted_at"], INITIAL_CLOCK)

    response = api.create_grant(
        grant_payload(
            scenario["worker_id"],
            scenario["site_id"],
            scenario["prequalification_id"],
            "2026-10-01T00:00:00Z",
        ),
        scenario["contractor_headers"],
    )
    validate_error(response, ERR_ACCESS_WINDOW_OVERLAP, 409)

    site = validate_success(
        api.get_site(scenario["site_id"], scenario["manager_headers"])
    )
    assert_site_posture(site, granted_worker_count=1)


def test_cooldown_clears_exactly_at_24_hours_and_the_next_window_still_touches(build, api):
    """One second short is refused; exactly 24 hours later the badge issues.

    PRD Section 3.8: "The test is strict at the far end, so a clock sitting
    exactly 24 hours after the revocation passes while one second earlier is
    `ERR_ACCESS_COOLDOWN_ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/access_window_closed_interval_intersects_at_touching_endpoints_while_cooldown_clears_exactly_at_24h
    """
    scenario = _badged_worker(build)

    revoked = build.revoke_badge(scenario["grant"]["id"], scenario["client_id"])
    assert_grant_state(revoked, status="REVOKED", revocation_reason="CLIENT_REVOKED")
    assert_instant_equals(revoked["revoked_at"], INITIAL_CLOCK)
    site = validate_success(
        api.get_site(scenario["site_id"], scenario["manager_headers"])
    )
    assert_site_posture(site, granted_worker_count=0)

    build.set_clock("2026-08-01T23:59:59Z")
    too_soon = api.create_grant(
        grant_payload(
            scenario["worker_id"],
            scenario["site_id"],
            scenario["prequalification_id"],
            "2026-08-10T00:00:00Z",
        ),
        scenario["contractor_headers"],
    )
    validate_error(too_soon, ERR_ACCESS_COOLDOWN_ACTIVE, 409)

    build.set_clock("2026-08-02T00:00:00Z")
    second = validate_success(
        api.create_grant(
            grant_payload(
                scenario["worker_id"],
                scenario["site_id"],
                scenario["prequalification_id"],
                "2026-08-10T00:00:00Z",
            ),
            scenario["contractor_headers"],
        ),
        201,
    )
    assert_grant_state(second, status="GRANTED")
    assert_instant_equals(second["granted_at"], "2026-08-02T00:00:00Z")
    assert_instant_equals(second["expires_at"], "2026-08-10T00:00:00Z")
    site = validate_success(
        api.get_site(scenario["site_id"], scenario["manager_headers"])
    )
    assert_site_posture(site, granted_worker_count=1)

    # The clock now sits exactly on the live badge's expires_at, so the new
    # window shares that single instant with it.
    build.set_clock("2026-08-10T00:00:00Z")
    touching = api.create_grant(
        grant_payload(
            scenario["worker_id"],
            scenario["site_id"],
            scenario["prequalification_id"],
            "2026-09-01T00:00:00Z",
        ),
        scenario["contractor_headers"],
    )
    validate_error(touching, ERR_ACCESS_WINDOW_OVERLAP, 409)

    rows, meta = validate_paginated(
        api.list_grants(
            scenario["manager_headers"],
            {"worker_id": scenario["worker_id"], "site_id": scenario["site_id"]},
        )
    )
    assert meta["total_count"] == 2, (
        f"expected exactly two grant rows, got {meta['total_count']}"
    )
    assert len(rows) == 2
