"""Cross-cutting behaviour of the program contract and its consistency model.

This file covers the two declared optimistic-concurrency writes and the distinct
refusals they raise, the discipline of the package-decision cascade on both of
its branches, the three trip points of the consecutive-deficiency counter and
the reset that unwinds them, the reconciliation of the three agency-side
counters across a grant, a notice, an acceptance and a revocation, and the
immediate visibility of every derived figure a write computes.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import CSP_LEAD_HEADERS

#: The instant the assessment reports its finding, three weeks before the
#: authorization decision.
FINDING_DETECTED_AT = "2026-03-15T00:00:00Z"

#: The first three month-ends after the authorization month, at which the
#: matching monitoring period becomes closeable.
APRIL_FIRST = "2026-04-01T00:00:00Z"
MAY_FIRST = "2026-05-01T00:00:00Z"
JUNE_FIRST = "2026-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Shared state builders
# ---------------------------------------------------------------------------


def _authorized_offering_remembering_the_pre_package_version(client, findings=None):
    """Drive an offering to a live authorization, keeping the offering `version`
    the client observed just before the package was created."""
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env)
    env = fx.seed_report_delivered(
        client, env, findings=findings, report_at=fx.AUTHORIZATION_CLOCK
    )
    env["offering_version_before_package"] = fx.offering_version(
        client, env["offering_id"]
    )
    env = fx.seed_submitted_package(client, env)
    env = fx.decide_package(client, env, decision="AUTHORIZE")
    return env


def _package_under_review(client, findings=None):
    """Drive an offering to a package sitting in `UNDER_REVIEW`, undecided."""
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env)
    env = fx.seed_report_delivered(
        client, env, findings=findings, report_at=fx.AUTHORIZATION_CLOCK
    )
    return fx.seed_submitted_package(client, env)


def _package_ready_to_submit(client, findings=None):
    """Drive an offering to a `DRAFT` package that passes every submission gate."""
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env)
    env = fx.seed_report_delivered(
        client, env, findings=findings, report_at=fx.AUTHORIZATION_CLOCK
    )
    return fx.seed_package(client, env)


def _add_epa(client, env):
    """Register a second agency that holds no sponsorship of its own."""
    return fx.add_agency(
        client,
        env,
        name="Environmental Protection Agency",
        agency_code="EPA",
        key="epa",
    )


def _close_period_at(client, env, period_month, clock):
    """Move the clock to ``clock`` and close the named monitoring period."""
    fx.set_clock(client, clock)
    periods = fx.list_monitoring_periods(client, env["authorization_id"])
    target = next(row for row in periods if row["period_month"] == period_month)
    return fx.close_period(client, env, target["id"])


def _suspended_by_two_deficient_closes(client):
    """A live authorization taken to `SUSPENDED` by two scan-less period closes."""
    env = fx.seed_authorized_offering(client)
    _close_period_at(client, env, "2026-03", APRIL_FIRST)
    _close_period_at(client, env, "2026-04", MAY_FIRST)
    return env


# ---------------------------------------------------------------------------
# The two declared optimistic-concurrency rules
# ---------------------------------------------------------------------------


def test_package_create_carrying_the_pre_package_offering_version_is_refused_as_stale(
    client,
):
    """A package create replaying the offering version observed before the first
    package is refused with the offering-parented stale-version error.

    PRD: "If that value does not equal the offering's current `version`, the create is rejected with `ERR_STALE_OFFERING_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/both_declared_occ_rules_reject_a_stale_parent_version_and_accept_the_current_one
    """
    env = _authorized_offering_remembering_the_pre_package_version(client)
    stale_version = env["offering_version_before_package"]
    current_version = fx.offering_version(client, env["offering_id"])
    assert stale_version != current_version, (
        "the prelude must leave the observed offering version behind the current one"
    )

    response = client.create_package(
        f.build_package_payload(
            env["offering_id"], env["engagement_id"], stale_version
        ),
        env["lead_headers"],
    )
    validate_error(response, err.ERR_STALE_OFFERING_VERSION, 412)

    # The refusal wrote nothing: no second package row, no version bump.
    a.assert_integer(
        fx.offering_version(client, env["offering_id"]),
        current_version,
        "offering.version after the refused create",
    )
    _, meta = validate_paginated(
        client.list_packages(CSP_LEAD_HEADERS, {"offering_id": env["offering_id"]})
    )
    assert meta["total_count"] == 1, "the refused create must not have added a package"


def test_reuse_grant_accepts_the_current_authorization_version_and_refuses_it_once_stale(
    client,
):
    """The authorization version that buys the first reuse seat is stale for the
    second grant, which is refused with the authorization-parented error.

    PRD: "A mismatch with the authorization's current `version` is rejected with `ERR_STALE_AUTHORIZATION_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/both_declared_occ_rules_reject_a_stale_parent_version_and_accept_the_current_one
    """
    env = _authorized_offering_remembering_the_pre_package_version(client)
    env = _add_epa(client, env)
    env = fx.add_agency(
        client,
        env,
        name="Health and Human Services",
        agency_code="HHS",
        key="hhs",
    )
    observed_version = fx.authorization_version(client, env["authorization_id"])
    a.assert_integer(observed_version, 1, "authorization.version at issue")

    first = client.create_reuse_grant(
        f.build_reuse_grant_payload(
            env["authorization_id"], env["epa_id"], observed_version
        ),
        env["epa_headers"],
    )
    validate_success(first, 201)

    second = client.create_reuse_grant(
        f.build_reuse_grant_payload(
            env["authorization_id"], env["hhs_id"], observed_version
        ),
        env["hhs_headers"],
    )
    validate_error(second, err.ERR_STALE_AUTHORIZATION_VERSION, 412)

    refreshed_version = fx.authorization_version(client, env["authorization_id"])
    a.assert_integer(refreshed_version, 2, "authorization.version after one grant")

    retry = client.create_reuse_grant(
        f.build_reuse_grant_payload(
            env["authorization_id"], env["hhs_id"], refreshed_version
        ),
        env["hhs_headers"],
    )
    validate_success(retry, 201)

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(
        authorization["version"], 3, "authorization.version after two grants"
    )
    a.assert_integer(authorization["reuse_seats_granted"], 2, "reuse_seats_granted")
    a.assert_integer(authorization["reuse_seats_available"], 3, "reuse_seats_available")
    a.assert_all_invariants(authorization=authorization)


# ---------------------------------------------------------------------------
# The reject branch of the authorization decision
# ---------------------------------------------------------------------------


def test_rejected_package_mints_no_authorization_and_leaves_the_offering_package_submitted(
    client,
):
    """Rejecting a package closes it without minting an authorization letter, an
    authorization row or any move of the offering out of `PACKAGE_SUBMITTED`.

    PRD: "A `REJECT` decision moves the package `UNDER_REVIEW → REJECTED`, creates no authorization, and leaves the offering in `PACKAGE_SUBMITTED`."

    Design: Corner/cross_cutting_complexity_layers/the_reject_branch_of_the_decision_fires_none_of_the_four_cascade_links
    """
    env = _package_under_review(
        client, findings=[f.build_finding("AC-2", "LOW", FINDING_DETECTED_AT)]
    )

    package = validate_success(
        client.decide_package(
            env["package_id"],
            f.build_package_decision_payload(
                "REJECT", risk_acceptance_note=f.OMIT
            ),
            env["agency_headers"],
        ),
        200,
    )
    assert package["status"] == "REJECTED"
    assert package["letter_reference"] is None

    rows, meta = validate_paginated(
        client.list_authorizations(
            CSP_LEAD_HEADERS, {"offering_id": env["offering_id"]}
        )
    )
    assert meta["total_count"] == 0, "the reject branch must create no authorization"
    assert rows == []

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "PACKAGE_SUBMITTED"
    assert offering["status"] != "AUTHORIZED"
    a.assert_integer(offering["open_package_count"], 0, "open_package_count")


def test_rejected_package_leaves_the_assessment_finding_anchored_at_its_detection_instant(
    client,
):
    """The re-anchoring of assessment findings belongs to the authorize branch, so
    a rejected package leaves anchor and deadline exactly where the report set them.

    PRD: "Items sourced from an assessment are re-anchored once, at the moment the offering is authorized: for an item whose `source` is `ASSESSMENT`, whose `remediation_status` is not `CLOSED`, and whose `detected_at` falls strictly before the authorization instant, `anchor_at` is moved forward to that authorization instant and `deadline_at` is recomputed from it."

    Design: Corner/cross_cutting_complexity_layers/the_reject_branch_of_the_decision_fires_none_of_the_four_cascade_links
    """
    env = _package_under_review(
        client, findings=[f.build_finding("AC-2", "LOW", FINDING_DETECTED_AT)]
    )
    items = fx.list_poam_items(client, offering_id=env["offering_id"])
    assert len(items) == 1
    item_id = items[0]["id"]

    validate_success(
        client.decide_package(
            env["package_id"],
            f.build_package_decision_payload(
                "REJECT", risk_acceptance_note=f.OMIT
            ),
            env["agency_headers"],
        ),
        200,
    )

    item = fx.read_poam_item(client, item_id)
    assert item["source"] == "ASSESSMENT"
    assert item["remediation_status"] == "OPEN"
    a.assert_instant(item["anchor_at"], FINDING_DETECTED_AT, "anchor_at")
    a.assert_instant(
        item["deadline_at"],
        a.expected_deadline(FINDING_DETECTED_AT, "LOW"),
        "deadline_at",
    )
    assert not a.instants_equal(item["anchor_at"], fx.AUTHORIZATION_CLOCK), (
        "a rejected package must not re-anchor the finding to the decision instant"
    )


# ---------------------------------------------------------------------------
# The consecutive-deficiency counter and its three trip points
# ---------------------------------------------------------------------------


def _authorized_with_a_notifiable_grant(client):
    """A live authorization whose only reuse grant is notifiable."""
    env = fx.seed_authorized_offering(client)
    env = _add_epa(client, env)
    return fx.seed_reuse_grant(
        client,
        env,
        agency_id=env["epa_id"],
        agency_headers=env["epa_headers"],
        advance_to="PACKAGE_ACCESS_GRANTED",
    )


def test_first_deficient_month_moves_the_posture_and_issues_the_reuse_notice(client):
    """One scan-less month puts the authorization at risk and notifies the
    grantee agency without touching the authorization status.

    PRD: "At a run of 1 the `monitoring_posture` moves `ACTIVE → AT_RISK`, and every reuse grant of the authorization in `PACKAGE_ACCESS_GRANTED`, `INCREMENTAL_REVIEW` or `REUSE_ACCEPTED` is moved to `NOTICE_ISSUED`, each such grant incrementing its own `notice_count` by one and the grantee agency's `open_notice_count` by one."

    Design: Corner/cross_cutting_complexity_layers/the_consecutive_deficiency_counter_revokes_only_on_its_third_increment
    """
    env = _authorized_with_a_notifiable_grant(client)

    closed = _close_period_at(client, env, "2026-03", APRIL_FIRST)
    assert closed["status"] == "CLOSED_DEFICIENT"

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(
        authorization["consecutive_deficient_periods"], 1, "consecutive_deficient_periods"
    )
    assert authorization["monitoring_posture"] == "AT_RISK"
    assert authorization["authorization_status"] == "AUTHORIZED"

    grant = fx.read_reuse_grant(client, env["grant_id"])
    assert grant["access_state"] == "NOTICE_ISSUED"
    a.assert_integer(grant["notice_count"], 1, "notice_count")

    agency = fx.read_agency(client, env["epa_id"])
    a.assert_integer(agency["open_notice_count"], 1, "open_notice_count")

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "AUTHORIZED", (
        "a single deficient month must not suspend the offering"
    )


def test_second_deficient_month_suspends_both_the_authorization_and_the_offering(client):
    """The second consecutive scan-less month escalates the posture and suspends
    the authorization and its offering together.

    PRD: "At a run of exactly 2 the `authorization_status` moves `AUTHORIZED → SUSPENDED` and the `monitoring_posture` is set to `ESCALATED`, and the offering is driven `AUTHORIZED → SUSPENDED` with its `version` incremented by one; a posture already at `AT_RISK` moving on a run of 2 or more likewise lands at `ESCALATED` and issues notices to the same three access states."

    Design: Corner/cross_cutting_complexity_layers/the_consecutive_deficiency_counter_revokes_only_on_its_third_increment
    """
    env = _authorized_with_a_notifiable_grant(client)
    _close_period_at(client, env, "2026-03", APRIL_FIRST)

    closed = _close_period_at(client, env, "2026-04", MAY_FIRST)
    assert closed["status"] == "CLOSED_DEFICIENT"

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(
        authorization["consecutive_deficient_periods"], 2, "consecutive_deficient_periods"
    )
    assert authorization["monitoring_posture"] == "ESCALATED"
    assert authorization["authorization_status"] == "SUSPENDED"
    assert authorization["authorization_status"] != "REVOKED", (
        "revocation is two increments away from the first consequence"
    )

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "SUSPENDED"

    # The notice population is exactly the three named access states, and the
    # grant already sits outside them in NOTICE_ISSUED.
    grant = fx.read_reuse_grant(client, env["grant_id"])
    assert grant["access_state"] == "NOTICE_ISSUED"
    a.assert_integer(grant["notice_count"], 1, "notice_count")


def test_third_deficient_month_revokes_the_authorization_and_returns_every_seat(client):
    """The third consecutive scan-less month revokes the authorization, revokes
    every live grant with the cascade reason and hands back the seats.

    PRD: "At a run of 3 or more the `authorization_status` moves to `REVOKED` from either `AUTHORIZED` or `SUSPENDED`, and every reuse grant of the authorization not already revoked is moved to `REVOKED` with `revoked_reason` `AUTHORIZATION_REVOKED`, each returning its seat to the pool per §2.11."

    Design: Corner/cross_cutting_complexity_layers/the_consecutive_deficiency_counter_revokes_only_on_its_third_increment
    """
    env = _authorized_with_a_notifiable_grant(client)
    _close_period_at(client, env, "2026-03", APRIL_FIRST)
    _close_period_at(client, env, "2026-04", MAY_FIRST)

    closed = _close_period_at(client, env, "2026-05", JUNE_FIRST)
    assert closed["status"] == "CLOSED_DEFICIENT"

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(
        authorization["consecutive_deficient_periods"], 3, "consecutive_deficient_periods"
    )
    assert authorization["authorization_status"] == "REVOKED"
    a.assert_integer(
        authorization["reuse_seats_granted"], 0, "reuse_seats_granted after revocation"
    )
    a.assert_integer(
        authorization["reuse_seats_available"],
        c.REUSE_SEATS_TOTAL_DEFAULT,
        "reuse_seats_available after revocation",
    )
    a.assert_all_invariants(authorization=authorization)

    grant = fx.read_reuse_grant(client, env["grant_id"])
    assert grant["access_state"] == "REVOKED"
    assert grant["revoked_reason"] == "AUTHORIZATION_REVOKED"

    agency = fx.read_agency(client, env["epa_id"])
    a.assert_integer(agency["reuse_grant_count"], 0, "reuse_grant_count")
    a.assert_integer(agency["open_notice_count"], 0, "open_notice_count")

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "SUSPENDED", (
        "revocation declares no further transition for the offering"
    )


def test_revocation_stops_the_auto_creation_of_the_next_monitoring_period(client):
    """Once the authorization is revoked no further month is opened, so the
    period ledger freezes at the three months that were closed.

    PRD: "And the next month's monitoring period is auto-created by the close whenever the authorization's `authorization_status` after the close is `AUTHORIZED` or `SUSPENDED` — that creation is skipped when a period for that `period_month` already exists for the authorization, and no further period is auto-created once the authorization has reached `REVOKED` or `EXPIRED`."

    Design: Corner/cross_cutting_complexity_layers/the_consecutive_deficiency_counter_revokes_only_on_its_third_increment
    """
    env = _authorized_with_a_notifiable_grant(client)
    _close_period_at(client, env, "2026-03", APRIL_FIRST)
    _close_period_at(client, env, "2026-04", MAY_FIRST)
    _close_period_at(client, env, "2026-05", JUNE_FIRST)

    periods, meta = validate_paginated(
        client.list_monitoring_periods(env["authorization_id"], CSP_LEAD_HEADERS)
    )
    assert meta["total_count"] == 3, (
        "no fourth month may be opened after the revocation"
    )
    assert [row["period_month"] for row in periods] == [
        "2026-03",
        "2026-04",
        "2026-05",
    ]
    assert all(row["status"] == "CLOSED_DEFICIENT" for row in periods)


# ---------------------------------------------------------------------------
# The restorative compliant close
# ---------------------------------------------------------------------------


def test_one_compliant_month_resets_the_counter_and_lifts_the_suspension(client):
    """A single compliant close returns the deficiency counter to zero, the
    posture to active and both authorization and offering out of suspension.

    PRD: "It resets the authorization's `consecutive_deficient_periods` to 0, moves `monitoring_posture` `AT_RISK → ACTIVE` where applicable, and moves `authorization_status` `SUSPENDED → AUTHORIZED` where applicable — with that last move driving the offering `SUSPENDED → AUTHORIZED` and incrementing the offering's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/a_single_compliant_close_resets_the_counter_and_lifts_the_suspension
    """
    env = _suspended_by_two_deficient_closes(client)
    suspended = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(
        suspended["consecutive_deficient_periods"], 2, "consecutive_deficient_periods"
    )
    assert suspended["authorization_status"] == "SUSPENDED"
    assert suspended["monitoring_posture"] == "ESCALATED"

    may = next(
        row
        for row in fx.list_monitoring_periods(client, env["authorization_id"])
        if row["period_month"] == "2026-05"
    )
    fx.submit_scans(client, env, may["id"])

    closed = _close_period_at(client, env, "2026-05", JUNE_FIRST)
    assert closed["status"] == "CLOSED_COMPLIANT"

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(
        authorization["consecutive_deficient_periods"],
        0,
        "consecutive_deficient_periods after the compliant close",
    )
    assert authorization["authorization_status"] == "AUTHORIZED"

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "AUTHORIZED"


def test_monthly_scans_are_accepted_on_time_while_the_authorization_is_suspended(client):
    """Scan submission is not gated on the authorization being active, so a
    suspended provider can still deliver its month on time.

    PRD: "The submission's `status` follows directly from that figure — `ACCEPTED` when `days_late` is 0, `LATE_ACCEPTED` when `days_late` is 1, 2 or 3, and `REJECTED` when `days_late` is 4 or more."

    Design: Corner/cross_cutting_complexity_layers/a_single_compliant_close_resets_the_counter_and_lifts_the_suspension
    """
    env = _suspended_by_two_deficient_closes(client)
    may = next(
        row
        for row in fx.list_monitoring_periods(client, env["authorization_id"])
        if row["period_month"] == "2026-05"
    )
    a.assert_monitoring_window(may, "2026-05")

    submission = validate_success(
        client.create_scan_submission(
            may["id"], f.build_scan_submission_payload(), env["lead_headers"]
        ),
        201,
    )
    a.assert_integer(submission["days_late"], 0, "days_late")
    assert submission["status"] == a.expected_scan_status(0) == "ACCEPTED"

    period = fx.read_monitoring_period(client, may["id"])
    a.assert_integer(period["accepted_submission_count"], 1, "accepted_submission_count")
    assert period["covered_scan_types"] == sorted(c.MANDATORY_SCAN_TYPES)


def test_compliant_close_still_opens_the_following_month(client):
    """The restorative close leaves the authorization active, so the next month
    is opened as usual.

    PRD: "And the next month's monitoring period is auto-created by the close whenever the authorization's `authorization_status` after the close is `AUTHORIZED` or `SUSPENDED` — that creation is skipped when a period for that `period_month` already exists for the authorization, and no further period is auto-created once the authorization has reached `REVOKED` or `EXPIRED`."

    Design: Corner/cross_cutting_complexity_layers/a_single_compliant_close_resets_the_counter_and_lifts_the_suspension
    """
    env = _suspended_by_two_deficient_closes(client)
    may = next(
        row
        for row in fx.list_monitoring_periods(client, env["authorization_id"])
        if row["period_month"] == "2026-05"
    )
    fx.submit_scans(client, env, may["id"])
    _close_period_at(client, env, "2026-05", JUNE_FIRST)

    periods, meta = validate_paginated(
        client.list_monitoring_periods(env["authorization_id"], CSP_LEAD_HEADERS)
    )
    assert meta["total_count"] == 4
    june = periods[3]
    assert june["period_month"] == "2026-06"
    assert june["status"] == "OPEN"
    a.assert_monitoring_window(june, "2026-06")


# ---------------------------------------------------------------------------
# The three agency-side counters
# ---------------------------------------------------------------------------


def test_sponsoring_an_offering_does_not_populate_the_reuse_counters(client):
    """Sponsorship and reuse are counted on separate agency counters: the sponsor
    holds no grant and the grantee sponsors nothing.

    PRD: "An agency's `sponsored_offering_count` counts the offerings whose `sponsor_agency_id` is that agency; its `reuse_grant_count` counts that agency's reuse grants whose `access_state` is not `REVOKED`; its `open_notice_count` counts that agency's grants currently in `access_state` `NOTICE_ISSUED`."

    Design: Corner/cross_cutting_complexity_layers/the_agency_side_counters_reconcile_after_a_grant_a_notice_an_acceptance_and_a_revoke
    """
    env = fx.seed_authorized_offering(client)
    env = _add_epa(client, env)

    sponsor = fx.read_agency(client, env["agency_id"])
    a.assert_integer(sponsor["sponsored_offering_count"], 1, "sponsored_offering_count")
    a.assert_integer(sponsor["reuse_grant_count"], 0, "sponsor reuse_grant_count")
    a.assert_integer(sponsor["open_notice_count"], 0, "sponsor open_notice_count")

    env = fx.seed_reuse_grant(
        client,
        env,
        agency_id=env["epa_id"],
        agency_headers=env["epa_headers"],
        advance_to="REQUESTED",
    )

    grantee = fx.read_agency(client, env["epa_id"])
    a.assert_integer(grantee["reuse_grant_count"], 1, "grantee reuse_grant_count")
    a.assert_integer(grantee["open_notice_count"], 0, "grantee open_notice_count")
    a.assert_integer(
        grantee["sponsored_offering_count"], 0, "grantee sponsored_offering_count"
    )

    sponsor_after = fx.read_agency(client, env["agency_id"])
    a.assert_integer(
        sponsor_after["reuse_grant_count"], 0, "sponsor reuse_grant_count after a grant"
    )
    a.assert_integer(
        sponsor_after["sponsored_offering_count"],
        1,
        "sponsored_offering_count after a grant",
    )


def test_accepting_reuse_out_of_a_notice_clears_the_agency_notice_counter(client):
    """The deficient close raises the grantee's open notice counter and the
    acceptance from `NOTICE_ISSUED` is what puts it back.

    PRD: "It writes `incremental_review_findings_count` and `reuse_accepted_at` from the logical clock and moves the grant to `REUSE_ACCEPTED`; when the previous state was `NOTICE_ISSUED`, accepting also decrements the grantee agency's `open_notice_count` by one, which is the loop back out of a monitoring notice into good standing."

    Design: Corner/cross_cutting_complexity_layers/the_agency_side_counters_reconcile_after_a_grant_a_notice_an_acceptance_and_a_revoke
    """
    env = _authorized_with_a_notifiable_grant(client)
    _close_period_at(client, env, "2026-03", APRIL_FIRST)

    notified = fx.read_agency(client, env["epa_id"])
    a.assert_integer(notified["open_notice_count"], 1, "open_notice_count under notice")
    a.assert_integer(
        fx.read_reuse_grant(client, env["grant_id"])["notice_count"], 1, "notice_count"
    )

    accepted = validate_success(
        client.record_incremental_review(
            env["grant_id"],
            f.build_incremental_review_payload(
                "ACCEPT", c.INCREMENTAL_FINDINGS_TOLERANCE
            ),
            env["epa_headers"],
        ),
        200,
    )
    assert accepted["access_state"] == "REUSE_ACCEPTED"
    a.assert_instant(accepted["reuse_accepted_at"], APRIL_FIRST, "reuse_accepted_at")
    a.assert_integer(
        accepted["incremental_review_findings_count"],
        c.INCREMENTAL_FINDINGS_TOLERANCE,
        "incremental_review_findings_count",
    )
    a.assert_integer(accepted["notice_count"], 1, "notice_count after the acceptance")

    cleared = fx.read_agency(client, env["epa_id"])
    a.assert_integer(
        cleared["open_notice_count"], 0, "open_notice_count after the acceptance"
    )
    a.assert_integer(cleared["reuse_grant_count"], 1, "reuse_grant_count")


def test_revoking_the_grant_returns_the_seat_and_leaves_the_sponsorship_counter_alone(
    client,
):
    """Revocation hands back the seat and the grant counter while the notice
    counter, already cleared by the acceptance, stays at zero.

    PRD: "It returns the seat — the authorization's `reuse_seats_granted` decreases by one and `reuse_seats_available` increases by one — decrements the agency's `reuse_grant_count` by one, decrements that agency's `open_notice_count` by one when the grant was sitting in `NOTICE_ISSUED`, and increments the authorization's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/the_agency_side_counters_reconcile_after_a_grant_a_notice_an_acceptance_and_a_revoke
    """
    env = _authorized_with_a_notifiable_grant(client)
    _close_period_at(client, env, "2026-03", APRIL_FIRST)
    validate_success(
        client.record_incremental_review(
            env["grant_id"],
            f.build_incremental_review_payload(
                "ACCEPT", c.INCREMENTAL_FINDINGS_TOLERANCE
            ),
            env["epa_headers"],
        ),
        200,
    )
    version_before_revoke = fx.authorization_version(client, env["authorization_id"])

    revoked = validate_success(
        client.revoke_reuse_grant(
            env["grant_id"], f.build_revoke_payload("AGENCY_REQUEST"), env["epa_headers"]
        ),
        200,
    )
    assert revoked["access_state"] == "REVOKED"
    assert revoked["revoked_reason"] == "AGENCY_REQUEST"

    grantee = fx.read_agency(client, env["epa_id"])
    a.assert_integer(
        grantee["reuse_grant_count"], 0, "reuse_grant_count after the revoke"
    )
    a.assert_integer(
        grantee["open_notice_count"], 0, "open_notice_count after the revoke"
    )

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["reuse_seats_granted"], 0, "reuse_seats_granted")
    a.assert_integer(
        authorization["reuse_seats_available"],
        c.REUSE_SEATS_TOTAL_DEFAULT,
        "reuse_seats_available",
    )
    a.assert_integer(
        authorization["version"],
        version_before_revoke + 1,
        "authorization.version after the revoke",
    )
    a.assert_all_invariants(authorization=authorization)

    sponsor = fx.read_agency(client, env["agency_id"])
    a.assert_integer(
        sponsor["sponsored_offering_count"],
        1,
        "sponsored_offering_count is untouched by the reuse workflow",
    )


# ---------------------------------------------------------------------------
# Immediate consistency: writes carry what their own side effects derived
# ---------------------------------------------------------------------------


def test_submit_response_already_carries_the_figures_its_own_side_effects_froze(client):
    """The submission response itself reports the coverage, risk and finding
    figures frozen by that same call.

    PRD: "Three figures are frozen onto the package at that instant and never move again: `crm_coverage_pct` from the coverage computation, `residual_risk_score_at_submission` from the submission variant of the risk score, and `open_findings_at_submission` as the count of the offering's findings whose `remediation_status` is not `CLOSED`."

    Design: Corner/consistency_model/every_write_response_already_carries_the_fields_its_own_side_effects_derived
    """
    env = _package_ready_to_submit(
        client, findings=[f.build_finding("AC-2", "LOW", FINDING_DETECTED_AT)]
    )
    draft = fx.read_package(client, env["package_id"])
    assert draft["crm_coverage_pct"] is None
    assert draft["residual_risk_score_at_submission"] is None
    assert draft["open_findings_at_submission"] is None

    package = validate_success(
        client.submit_package(env["package_id"], env["lead_headers"]), 200
    )
    assert package["status"] == "SUBMITTED"
    a.assert_money(package["crm_coverage_pct"], 100.00, "crm_coverage_pct")
    a.assert_money(
        package["residual_risk_score_at_submission"],
        1.00,
        "residual_risk_score_at_submission",
    )
    a.assert_integer(
        package["open_findings_at_submission"], 1, "open_findings_at_submission"
    )
    a.assert_instant(package["submitted_at"], fx.AUTHORIZATION_CLOCK, "submitted_at")
    a.assert_integer(package["submission_round"], 1, "submission_round")

    # The very next read agrees with the write response, unchanged.
    stored = fx.read_package(client, env["package_id"])
    a.assert_money(stored["crm_coverage_pct"], 100.00, "crm_coverage_pct on read")
    a.assert_money(
        stored["residual_risk_score_at_submission"],
        1.00,
        "residual_risk_score_at_submission on read",
    )
    a.assert_integer(
        stored["open_findings_at_submission"], 1, "open_findings_at_submission on read"
    )


def test_decision_response_already_carries_the_letter_reference_it_minted(client):
    """The authorize decision returns the letter reference and the closed status
    in the same response that created them.

    PRD: "An `AUTHORIZE` decision moves the package `UNDER_REVIEW → AUTHORIZED` and mints its `letter_reference`, formatted as `AUTH-LTR-` followed by the package's `submission_round` and then by the sponsoring agency's `agency_code` on the sponsored path or the literal `BOARD` on the program-board path."

    Design: Corner/consistency_model/every_write_response_already_carries_the_fields_its_own_side_effects_derived
    """
    env = _package_ready_to_submit(
        client, findings=[f.build_finding("AC-2", "LOW", FINDING_DETECTED_AT)]
    )
    env = fx.submit_package(client, env)
    env = fx.review_package(client, env)

    package = validate_success(
        client.decide_package(
            env["package_id"],
            f.build_package_decision_payload("AUTHORIZE"),
            env["agency_headers"],
        ),
        200,
    )
    assert package["status"] == "AUTHORIZED"
    assert package["letter_reference"] == c.expected_letter_reference(
        1, env["agency_code"]
    )


def test_authorization_and_first_monitoring_period_are_queryable_on_the_next_call(client):
    """Every link of the authorize cascade is visible to the first read issued
    after the decision, with the logical clock unmoved.

    PRD: "Where §3 describes a chain — a package decision creating an authorization, that authorization creating the first monitoring period; a deficient period close incrementing a run counter, that counter moving the monitoring posture, that posture issuing reuse notices, those notices incrementing an agency counter — every link fires within the one request, not lazily and not on a subsequent read."

    Design: Corner/consistency_model/every_write_response_already_carries_the_fields_its_own_side_effects_derived
    """
    env = _package_ready_to_submit(
        client, findings=[f.build_finding("AC-2", "LOW", FINDING_DETECTED_AT)]
    )
    env = fx.submit_package(client, env)
    env = fx.review_package(client, env)
    offering_version_before = fx.offering_version(client, env["offering_id"])

    validate_success(
        client.decide_package(
            env["package_id"],
            f.build_package_decision_payload("AUTHORIZE"),
            env["agency_headers"],
        ),
        200,
    )

    rows, meta = validate_paginated(
        client.list_authorizations(
            CSP_LEAD_HEADERS, {"offering_id": env["offering_id"]}
        )
    )
    assert meta["total_count"] == 1
    authorization = rows[0]
    assert authorization["authorization_status"] == "AUTHORIZED"
    assert authorization["package_id"] == env["package_id"]
    a.assert_instant(
        authorization["authorized_at"], fx.AUTHORIZATION_CLOCK, "authorized_at"
    )

    periods, period_meta = validate_paginated(
        client.list_monitoring_periods(authorization["id"], CSP_LEAD_HEADERS)
    )
    assert period_meta["total_count"] == 1
    assert periods[0]["period_month"] == "2026-03"
    assert periods[0]["status"] == "OPEN"

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "AUTHORIZED"
    a.assert_integer(
        offering["version"], offering_version_before + 1, "offering.version"
    )


# ---------------------------------------------------------------------------
# Immediate consistency: a derived read reflects the preceding write
# ---------------------------------------------------------------------------


def _authorized_with_one_high_finding(client):
    """A live authorization carrying one open HIGH assessment finding."""
    env = fx.seed_authorized_offering(
        client, findings=[f.build_finding("AC-2", "HIGH", FINDING_DETECTED_AT)]
    )
    highs = fx.list_poam_items(
        client, offering_id=env["offering_id"], severity="HIGH"
    )
    assert len(highs) == 1
    env["high_item_id"] = highs[0]["id"]
    return env


def test_risk_summary_drops_to_zero_in_the_read_after_the_only_high_finding_closes(
    client,
):
    """Verifying closure of the sole high finding is reflected by the very next
    risk-summary read, with no retry and no clock movement.

    PRD: "`VERIFY_CLOSE` moves `AWAITING_VERIFICATION → CLOSED`, sets `closure_reason` to `REMEDIATED`, and recomputes the authorization's `open_findings_count`, `closed_findings_count` and `residual_risk_score`; it is refused with `ERR_DEVIATION_PENDING_ON_ITEM` while any deviation on the item is still in `SUBMITTED`, `BOARD_REVIEW` or `AGENCY_REVIEW`."

    Design: Corner/consistency_model/a_derived_read_reflects_the_write_made_by_the_immediately_preceding_call
    """
    env = _authorized_with_one_high_finding(client)
    reanchored = fx.read_poam_item(client, env["high_item_id"])
    a.assert_instant(reanchored["anchor_at"], fx.AUTHORIZATION_CLOCK, "anchor_at")
    a.assert_instant(
        reanchored["deadline_at"],
        a.expected_deadline(fx.AUTHORIZATION_CLOCK, "HIGH"),
        "deadline_at",
    )

    before = fx.read_risk_summary(client, env["authorization_id"])
    a.assert_money(before["residual_risk_score"], 10.00, "residual_risk_score")
    assert before["poam_risk_tier"] == "MODERATE"
    a.assert_integer(before["overdue_high_count"], 0, "overdue_high_count")
    a.assert_integer(before["open_findings_count"], 1, "open_findings_count")

    closed = fx.drive_remediation(
        client,
        env,
        env["high_item_id"],
        ["START", "SUBMIT_EVIDENCE", "VERIFY_CLOSE"],
    )
    assert closed["remediation_status"] == "CLOSED"
    assert closed["closure_reason"] == "REMEDIATED"
    assert closed["risk_disposition"] == "NONE"

    after = fx.read_risk_summary(client, env["authorization_id"])
    a.assert_money(
        after["residual_risk_score"], 0.00, "residual_risk_score after the closure"
    )
    assert after["poam_risk_tier"] == "NONE"
    a.assert_integer(after["open_findings_count"], 0, "open_findings_count")
    a.assert_money(
        after["stored_residual_risk_score"], 0.00, "stored_residual_risk_score"
    )
    a.assert_risk_tier_matches_score(after, "risk summary")

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["open_findings_count"], 0, "open_findings_count")
    a.assert_integer(authorization["closed_findings_count"], 1, "closed_findings_count")
    a.assert_money(
        authorization["residual_risk_score"], 0.00, "stored residual_risk_score"
    )
    a.assert_all_invariants(authorization=authorization)


def test_frozen_submission_snapshot_does_not_follow_the_live_risk_score_down(client):
    """The package's at-submission risk figure is a deliberate snapshot and stays
    put while the live score falls to zero.

    PRD: "Three figures are frozen onto the package at that instant and never move again: `crm_coverage_pct` from the coverage computation, `residual_risk_score_at_submission` from the submission variant of the risk score, and `open_findings_at_submission` as the count of the offering's findings whose `remediation_status` is not `CLOSED`."

    Design: Corner/consistency_model/a_derived_read_reflects_the_write_made_by_the_immediately_preceding_call
    """
    env = _authorized_with_one_high_finding(client)
    frozen_before = fx.read_package(client, env["package_id"])
    a.assert_money(
        frozen_before["residual_risk_score_at_submission"],
        10.00,
        "residual_risk_score_at_submission",
    )

    fx.drive_remediation(
        client,
        env,
        env["high_item_id"],
        ["START", "SUBMIT_EVIDENCE", "VERIFY_CLOSE"],
    )

    live = fx.read_risk_summary(client, env["authorization_id"])
    a.assert_money(live["residual_risk_score"], 0.00, "live residual_risk_score")

    frozen_after = fx.read_package(client, env["package_id"])
    a.assert_money(
        frozen_after["residual_risk_score_at_submission"],
        10.00,
        "residual_risk_score_at_submission after the closure",
    )
    a.assert_integer(
        frozen_after["open_findings_at_submission"], 1, "open_findings_at_submission"
    )
    assert (
        frozen_after["residual_risk_score_at_submission"]
        != live["residual_risk_score"]
    ), "the snapshot must not track the live score"
