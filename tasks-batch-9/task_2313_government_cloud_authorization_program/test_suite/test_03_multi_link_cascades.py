"""Multi-link cascades of the program API.

One request in this contract routinely walks a whole chain of rows. These tests
cover the three longest chains: the authorization decision that mints an
authorization, drives its offering, opens the first monitoring period and
re-anchors the assessment findings; the deficient monitoring close that walks a
run counter into the monitoring posture, out to the grantee agencies' notice
counters and on into the next month's period; and the replacement finding whose
creation closes the item it supersedes and re-partitions the authorization's
finding ledger.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx

# The assessment finding of the authorize-chain recipe: raised against AC-2 at
# MODERATE severity, detected four weeks before the authorization instant.
ASSESSMENT_DETECTED_AT = "2026-03-01T00:00:00Z"

#: anchor_at 2026-03-01 plus the 90-day MODERATE allowance.
PRE_DECISION_DEADLINE = "2026-05-30T00:00:00Z"

#: anchor_at re-anchored to 2026-03-30 plus the same 90-day allowance.
POST_DECISION_DEADLINE = "2026-06-28T00:00:00Z"


def _authorize_chain_env(client):
    """A live authorization carrying exactly one MODERATE assessment finding."""
    return fx.seed_authorized_offering(
        client,
        findings=[
            f.build_finding(
                control_id="AC-2",
                severity="MODERATE",
                detected_at=ASSESSMENT_DETECTED_AT,
            )
        ],
    )


# ---------------------------------------------------------------------------
# The four-link authorization decision
# ---------------------------------------------------------------------------


def test_authorize_decision_mints_the_authorization_row_with_a_1095_day_term(client):
    """The AUTHORIZE decision creates the authorization row with its instants, postures and seat ledger.

    PRD: "First, an **authorization** row is created: `offering_id` and `package_id` name their sources, `authorization_path` and `letter_reference` are carried across from the package, `impact_level` freezes the offering's `final_impact_level`, `authorized_at` is set to the logical clock, `expires_at` is set to 1095 days after `authorized_at`, `authorization_status` opens at `AUTHORIZED`, `monitoring_posture` opens at `ACTIVE`, `consecutive_deficient_periods` opens at 0, `reuse_seats_total` opens at 5 with `reuse_seats_granted` 0 and `reuse_seats_available` 5, and `total_findings_count`, `open_findings_count`, `closed_findings_count`, `risk_accepted_findings_count`, `residual_risk_score` and `poam_risk_tier` are computed from the offering's findings as they stand."

    Design: Difficulty/transitive_cascade/authorize_package_chain_mints_authorization_period_and_reanchors_assessment_findings
    """
    env = _authorize_chain_env(client)
    authorization = fx.read_authorization(client, env["authorization_id"])

    assert authorization["offering_id"] == env["offering_id"]
    assert authorization["package_id"] == env["package_id"]
    assert authorization["authorization_path"] == "AGENCY_SPONSORED"
    assert authorization["impact_level"] == "MODERATE"

    a.assert_instant(
        authorization["authorized_at"], fx.AUTHORIZATION_CLOCK, "authorized_at"
    )
    a.assert_instant(
        authorization["expires_at"],
        a.shift_instant(fx.AUTHORIZATION_CLOCK, days=c.AUTHORIZATION_TERM_DAYS),
        "expires_at",
    )

    assert authorization["authorization_status"] == "AUTHORIZED"
    assert authorization["monitoring_posture"] == "ACTIVE"
    a.assert_integer(
        authorization["consecutive_deficient_periods"], 0, "consecutive_deficient_periods"
    )
    a.assert_integer(authorization["reuse_seats_total"], 5, "reuse_seats_total")
    a.assert_integer(authorization["reuse_seats_granted"], 0, "reuse_seats_granted")
    a.assert_integer(authorization["reuse_seats_available"], 5, "reuse_seats_available")

    # The one MODERATE finding is open and not yet overdue, so it contributes
    # 4.00 and the tier sits in the LOW band.
    a.assert_integer(authorization["total_findings_count"], 1, "total_findings_count")
    a.assert_integer(authorization["open_findings_count"], 1, "open_findings_count")
    a.assert_integer(authorization["closed_findings_count"], 0, "closed_findings_count")
    a.assert_integer(
        authorization["risk_accepted_findings_count"], 0, "risk_accepted_findings_count"
    )
    a.assert_money(authorization["residual_risk_score"], 4.00, "residual_risk_score")
    assert authorization["poam_risk_tier"] == "LOW"
    a.assert_all_invariants(authorization=authorization)


def test_authorization_letter_reference_pairs_the_round_with_the_sponsor_agency_code(
    client,
):
    """A first-round sponsored authorization is lettered AUTH-LTR-1-DOT on both the package and the authorization.

    PRD: "An `AUTHORIZE` decision moves the package `UNDER_REVIEW → AUTHORIZED` and mints its `letter_reference`, formatted as `AUTH-LTR-` followed by the package's `submission_round` and then by the sponsoring agency's `agency_code` on the sponsored path or the literal `BOARD` on the program-board path."

    Design: Difficulty/transitive_cascade/authorize_package_chain_mints_authorization_period_and_reanchors_assessment_findings
    """
    env = _authorize_chain_env(client)
    package = fx.read_package(client, env["package_id"])
    authorization = fx.read_authorization(client, env["authorization_id"])

    expected = c.expected_letter_reference(1, env["agency_code"])
    assert expected == "AUTH-LTR-1-DOT"
    assert package["letter_reference"] == expected
    assert authorization["letter_reference"] == expected
    # The program-board form of the reference is not the one minted here.
    assert authorization["letter_reference"] != c.expected_letter_reference(1)


def test_authorize_decision_drives_the_offering_to_authorized(client):
    """Minting the authorization bubbles the offering out of PACKAGE_SUBMITTED and empties its open package count.

    PRD: "Second, that row's creation drives the offering `PACKAGE_SUBMITTED → AUTHORIZED` and increments the offering's `version` by one."

    Design: Difficulty/transitive_cascade/authorize_package_chain_mints_authorization_period_and_reanchors_assessment_findings
    """
    env = _authorize_chain_env(client)
    offering = fx.read_offering(client, env["offering_id"])
    package = fx.read_package(client, env["package_id"])

    assert offering["status"] == "AUTHORIZED"
    assert offering["status"] != "PACKAGE_SUBMITTED"
    a.assert_integer(offering["open_package_count"], 0, "open_package_count")
    a.assert_integer(offering["superseded_package_count"], 0, "superseded_package_count")
    assert package["status"] == "AUTHORIZED"


def test_authorized_package_keeps_the_figures_frozen_at_submission(client):
    """The decided package still carries the coverage, risk and open-finding figures frozen when it was submitted.

    PRD: "Three figures are frozen onto the package at that instant and never move again: `crm_coverage_pct` from the coverage computation, `residual_risk_score_at_submission` from the submission variant of the risk score, and `open_findings_at_submission` as the count of the offering's findings whose `remediation_status` is not `CLOSED`."

    Design: Difficulty/transitive_cascade/authorize_package_chain_mints_authorization_period_and_reanchors_assessment_findings
    """
    env = _authorize_chain_env(client)
    package = fx.read_package(client, env["package_id"])

    a.assert_integer(package["submission_round"], 1, "submission_round")
    a.assert_instant(package["submitted_at"], fx.AUTHORIZATION_CLOCK, "submitted_at")
    # AC 2 of 2 and SC 1 of 1 documented gives a weighted 100.00.
    a.assert_money(package["crm_coverage_pct"], 100.00, "crm_coverage_pct")
    # The submission variant measures the MODERATE finding against its
    # assessment-time deadline of 2026-05-30, which 2026-03-30 has not reached.
    a.assert_money(
        package["residual_risk_score_at_submission"],
        4.00,
        "residual_risk_score_at_submission",
    )
    a.assert_integer(
        package["open_findings_at_submission"], 1, "open_findings_at_submission"
    )


def test_authorize_decision_opens_the_month_of_authorization_as_the_first_period(client):
    """The decision auto-creates exactly one monitoring period, for the calendar month holding authorized_at.

    PRD: "Third, the first monitoring period is created for the calendar month containing `authorized_at`."

    Design: Difficulty/transitive_cascade/authorize_package_chain_mints_authorization_period_and_reanchors_assessment_findings
    """
    env = _authorize_chain_env(client)
    periods = fx.list_monitoring_periods(client, env["authorization_id"])

    assert len(periods) == 1, f"expected exactly one monitoring period, got {periods}"
    period = periods[0]
    assert period["authorization_id"] == env["authorization_id"]
    assert period["status"] == "OPEN"
    # 2026-03 runs 2026-03-01 inclusive to 2026-04-01 exclusive, with scans due
    # five days later on 2026-04-06.
    a.assert_monitoring_window(period, "2026-03")
    assert period["covered_scan_types"] == []
    assert period["closed_at"] is None


def test_authorize_decision_reanchors_the_assessment_finding_to_the_authorization(client):
    """An open assessment finding detected before authorization is re-anchored to authorized_at and its deadline recomputed.

    PRD: "Fourth, every `ASSESSMENT`-sourced finding of the offering that is not `CLOSED` and whose `detected_at` precedes `authorized_at` is re-anchored to `authorized_at` and has its `deadline_at` recomputed, as described in §3.6."

    Design: Difficulty/transitive_cascade/authorize_package_chain_mints_authorization_period_and_reanchors_assessment_findings
    """
    env = _authorize_chain_env(client)

    # As read while the package was still awaiting its decision, the finding was
    # anchored on its detection instant.
    before = env["assessment_findings"][0]
    assert before["source"] == "ASSESSMENT"
    a.assert_instant(before["anchor_at"], ASSESSMENT_DETECTED_AT, "anchor_at before")
    a.assert_instant(before["deadline_at"], PRE_DECISION_DEADLINE, "deadline_at before")

    after = fx.read_poam_item(client, before["id"])
    assert after["source"] == "ASSESSMENT"
    assert after["remediation_status"] == "OPEN"
    a.assert_instant(after["detected_at"], ASSESSMENT_DETECTED_AT, "detected_at")
    a.assert_instant(after["anchor_at"], fx.AUTHORIZATION_CLOCK, "anchor_at after")
    a.assert_instant(
        after["deadline_at"],
        a.expected_deadline(fx.AUTHORIZATION_CLOCK, "MODERATE"),
        "deadline_at after",
    )
    a.assert_instant(after["deadline_at"], POST_DECISION_DEADLINE, "deadline_at after")
    # The pre-decision deadline is not the one that survives the cascade.
    assert not a.instants_equal(after["deadline_at"], PRE_DECISION_DEADLINE)


# ---------------------------------------------------------------------------
# The deficient monitoring close
# ---------------------------------------------------------------------------

#: The close is performed at the March period's scan due instant, which is
#: already past that period's window_end of 2026-04-01.
DEFICIENT_CLOSE_CLOCK = "2026-04-06T00:00:00Z"


def _deficient_close_env(client):
    """A live authorization whose 2026-03 period is closed with no scans filed.

    A second agency holds a reuse grant in ``PACKAGE_ACCESS_GRANTED`` so the
    notice leg of the chain has somewhere to land.
    """
    env = fx.seed_authorized_offering(client)
    env = fx.add_agency(
        client,
        env,
        name="Environmental Protection Agency",
        agency_code="EPA",
        key="grantee",
    )
    env = fx.seed_reuse_grant(
        client,
        env,
        agency_id=env["grantee_id"],
        advance_to="PACKAGE_ACCESS_GRANTED",
    )
    fx.set_clock(client, DEFICIENT_CLOSE_CLOCK)
    env["closed_period"] = fx.close_period(client, env, env["period_id"])
    return env


def test_close_with_no_scans_filed_lands_the_period_in_closed_deficient(client):
    """A period whose covered scan types never reached the mandatory three closes deficient.

    PRD: "When all three hold the period closes `OPEN → CLOSED_COMPLIANT`; when any one of them fails it closes `OPEN → CLOSED_DEFICIENT`."

    Design: Difficulty/transitive_cascade/deficient_period_close_chain_reaches_the_grantee_agency_notice_counter
    """
    env = _deficient_close_env(client)
    period = fx.read_monitoring_period(client, env["period_id"])

    assert period["status"] == "CLOSED_DEFICIENT"
    assert period["status"] != "CLOSED_COMPLIANT"
    a.assert_instant(period["closed_at"], DEFICIENT_CLOSE_CLOCK, "closed_at")
    # No submission was ever filed, so nothing covered the period and every
    # submission counter is still at its opening value.
    assert period["covered_scan_types"] == []
    a.assert_integer(
        period["accepted_submission_count"], 0, "accepted_submission_count"
    )
    a.assert_integer(period["late_submission_count"], 0, "late_submission_count")
    a.assert_integer(
        period["rejected_submission_count"], 0, "rejected_submission_count"
    )


def test_first_deficient_month_moves_the_posture_but_not_the_authorization_status(client):
    """One deficient month lifts the run counter to 1 and the posture to AT_RISK while the authorization stays AUTHORIZED.

    PRD: "A first deficient monitoring month moves the posture without touching the authorization status; a second one moves both."

    Design: Difficulty/transitive_cascade/deficient_period_close_chain_reaches_the_grantee_agency_notice_counter
    """
    env = _deficient_close_env(client)
    authorization = fx.read_authorization(client, env["authorization_id"])

    a.assert_integer(
        authorization["consecutive_deficient_periods"],
        c.DEFICIENT_RUN_AT_RISK,
        "consecutive_deficient_periods",
    )
    assert authorization["monitoring_posture"] == "AT_RISK"
    assert authorization["authorization_status"] == "AUTHORIZED"
    assert authorization["authorization_status"] != "SUSPENDED"
    # The offering follows the authorization status, which has not moved.
    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "AUTHORIZED"


def test_first_deficient_month_issues_a_notice_to_the_grantee_agency(client):
    """The deficient close moves the granted reuse grant to NOTICE_ISSUED and increments the grantee agency's open notice count.

    PRD: "At a run of 1 the `monitoring_posture` moves `ACTIVE → AT_RISK`, and every reuse grant of the authorization in `PACKAGE_ACCESS_GRANTED`, `INCREMENTAL_REVIEW` or `REUSE_ACCEPTED` is moved to `NOTICE_ISSUED`, each such grant incrementing its own `notice_count` by one and the grantee agency's `open_notice_count` by one."

    Design: Difficulty/transitive_cascade/deficient_period_close_chain_reaches_the_grantee_agency_notice_counter
    """
    env = _deficient_close_env(client)
    grant = fx.read_reuse_grant(client, env["grant_id"])

    assert grant["access_state"] == "NOTICE_ISSUED"
    a.assert_integer(grant["notice_count"], 1, "notice_count")

    grantee = fx.read_agency(client, env["grantee_id"])
    a.assert_integer(grantee["open_notice_count"], 1, "grantee open_notice_count")
    a.assert_integer(grantee["reuse_grant_count"], 1, "grantee reuse_grant_count")

    # The sponsoring agency holds no reuse grant, so no notice reaches it.
    sponsor = fx.read_agency(client, env["agency_id"])
    a.assert_integer(sponsor["open_notice_count"], 0, "sponsor open_notice_count")
    a.assert_integer(sponsor["reuse_grant_count"], 0, "sponsor reuse_grant_count")

    # A notice is not a revocation, so the seat stays with the grantee.
    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["reuse_seats_granted"], 1, "reuse_seats_granted")
    a.assert_integer(authorization["reuse_seats_available"], 4, "reuse_seats_available")
    a.assert_seat_conservation(authorization)


def test_deficient_close_auto_creates_the_following_month_period(client):
    """Closing the March period while the authorization remains AUTHORIZED opens the April period behind it.

    PRD: "And the next month's monitoring period is auto-created by the close whenever the authorization's `authorization_status` after the close is `AUTHORIZED` or `SUSPENDED` — that creation is skipped when a period for that `period_month` already exists for the authorization, and no further period is auto-created once the authorization has reached `REVOKED` or `EXPIRED`."

    Design: Difficulty/transitive_cascade/deficient_period_close_chain_reaches_the_grantee_agency_notice_counter
    """
    env = _deficient_close_env(client)
    periods = fx.list_monitoring_periods(client, env["authorization_id"])

    assert len(periods) == 2, f"expected two monitoring periods, got {periods}"
    months = sorted(period["period_month"] for period in periods)
    assert months == ["2026-03", "2026-04"]

    successors = [p for p in periods if p["period_month"] == "2026-04"]
    assert len(successors) == 1
    successor = successors[0]
    assert successor["id"] != env["period_id"]
    assert successor["status"] == "OPEN"
    # 2026-04 runs 2026-04-01 inclusive to 2026-05-01 exclusive, scans due
    # five days later on 2026-05-06.
    a.assert_monitoring_window(successor, "2026-04")
    assert successor["covered_scan_types"] == []


# ---------------------------------------------------------------------------
# Supersession of a finding
# ---------------------------------------------------------------------------

#: A HIGH finding raised at the authorization instant: 30 days of allowance.
SUPERSEDE_DETECTED_AT = "2026-03-30T00:00:00Z"
SUPERSEDE_DEADLINE = "2026-04-29T00:00:00Z"


def _supersede_env(client):
    """A live authorization carrying one HIGH finding replaced by a second one."""
    env = fx.seed_authorized_offering(client)
    env = fx.seed_poam_item(
        client,
        env,
        control_id="AC-2",
        severity="HIGH",
        detected_at=SUPERSEDE_DETECTED_AT,
        source="SELF_IDENTIFIED",
        key="replaced",
    )
    response = client.create_poam_item(
        f.build_poam_item_payload(
            env["offering_id"],
            control_id="AC-2r",
            severity="HIGH",
            detected_at=SUPERSEDE_DETECTED_AT,
            source="SELF_IDENTIFIED",
            supersedes_item_id=env["replaced_id"],
        ),
        env["lead_headers"],
    )
    env["replacement"] = validate_success(response, 201)
    env["replacement_id"] = env["replacement"]["id"]
    return env


def test_replacement_finding_opens_with_its_own_deadline_and_names_what_it_replaces(
    client,
):
    """The replacement finding is created OPEN, anchored on its own detection instant, pointing at the item it supersedes.

    PRD: "At creation an item's `anchor_at` equals its `detected_at`, and its `deadline_at` is `anchor_at` advanced by the severity base allowance and then by `granted_extension_days` further days."

    Design: Difficulty/transitive_cascade/supersede_item_chain_closes_the_replaced_finding_and_reconciles_the_authorization_ledger
    """
    env = _supersede_env(client)
    replacement = fx.read_poam_item(client, env["replacement_id"])

    assert replacement["supersedes_item_id"] == env["replaced_id"]
    assert replacement["remediation_status"] == "OPEN"
    assert replacement["risk_disposition"] == "NONE"
    assert replacement["closure_reason"] is None
    a.assert_integer(replacement["granted_extension_days"], 0, "granted_extension_days")
    a.assert_instant(replacement["anchor_at"], SUPERSEDE_DETECTED_AT, "anchor_at")
    a.assert_instant(
        replacement["deadline_at"],
        a.expected_deadline(SUPERSEDE_DETECTED_AT, "HIGH"),
        "deadline_at",
    )
    a.assert_instant(replacement["deadline_at"], SUPERSEDE_DEADLINE, "deadline_at")

    # The pointer is what the supersedes filter selects on.
    matches = fx.list_poam_items(client, supersedes_item_id=env["replaced_id"])
    assert a.ids_of(matches) == [env["replacement_id"]]


def test_superseded_finding_is_closed_with_reason_superseded(client):
    """The replaced finding is driven CLOSED with closure_reason SUPERSEDED while its risk dimension stays put.

    PRD: "When the pointer is good, the superseded item — whatever its current remediation dimension among `OPEN`, `IN_REMEDIATION` and `AWAITING_VERIFICATION` — is driven to `remediation_status` `CLOSED` with `closure_reason` `SUPERSEDED`, and the authorization's finding counters and residual risk score are recomputed in the same request when the offering is authorized."

    Design: Difficulty/transitive_cascade/supersede_item_chain_closes_the_replaced_finding_and_reconciles_the_authorization_ledger
    """
    env = _supersede_env(client)
    replaced = fx.read_poam_item(client, env["replaced_id"])

    assert replaced["remediation_status"] == "CLOSED"
    assert replaced["closure_reason"] == "SUPERSEDED"
    # Closure by supersession is neither a remediation nor a false positive.
    assert replaced["closure_reason"] != "REMEDIATED"
    # The risk dimension does not move with the remediation dimension.
    assert replaced["risk_disposition"] == "NONE"
    a.assert_integer(replaced["reopen_count"], 0, "reopen_count")


def test_supersession_repartitions_the_authorization_finding_ledger(client):
    """The authorization's ledger moves to two findings, one open and one closed, in the same request.

    PRD: "For any offering, `total_findings_count` on its authorization always equals `open_findings_count` plus `closed_findings_count`."

    Design: Difficulty/transitive_cascade/supersede_item_chain_closes_the_replaced_finding_and_reconciles_the_authorization_ledger
    """
    env = _supersede_env(client)
    authorization = fx.read_authorization(client, env["authorization_id"])

    a.assert_integer(authorization["total_findings_count"], 2, "total_findings_count")
    a.assert_integer(authorization["open_findings_count"], 1, "open_findings_count")
    a.assert_integer(authorization["closed_findings_count"], 1, "closed_findings_count")
    a.assert_finding_partition(authorization)


def test_supersession_holds_residual_risk_at_the_single_remaining_high_finding(client):
    """With the closed item out of the population, residual risk stays at the one HIGH finding's 10.00.

    PRD: "The included population is the offering's findings whose `remediation_status` is `OPEN`, `IN_REMEDIATION` or `AWAITING_VERIFICATION`; a `CLOSED` finding never contributes regardless of its `closure_reason`."

    Design: Difficulty/transitive_cascade/supersede_item_chain_closes_the_replaced_finding_and_reconciles_the_authorization_ledger
    """
    env = _supersede_env(client)
    authorization = fx.read_authorization(client, env["authorization_id"])

    # One open HIGH finding, not overdue as of 2026-03-30, weighs 10.00; the
    # superseded twin does not double the figure to 20.00.
    a.assert_money(authorization["residual_risk_score"], 10.00, "residual_risk_score")
    assert authorization["poam_risk_tier"] == "MODERATE"
    a.assert_risk_tier_matches_score(authorization)

    summary = fx.read_risk_summary(client, env["authorization_id"])
    a.assert_money(summary["residual_risk_score"], 10.00, "summary residual_risk_score")
    a.assert_integer(summary["open_findings_count"], 1, "summary open_findings_count")
    a.assert_integer(summary["overdue_high_count"], 0, "overdue_high_count")
