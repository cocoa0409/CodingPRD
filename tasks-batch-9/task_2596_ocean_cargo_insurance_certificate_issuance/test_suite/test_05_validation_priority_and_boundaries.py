"""
The order in which refusals are reported, and the exact edges of two limits.

Two operations here can fail several ways at once — issuing a certificate on a
hull that is both uninsurable and full, and declaring a shipment that both
breaches its packaging warranty and asks for too large a share of a conveyance.
Each is exercised twice: once with both conditions true, to pin which error the
client sees, and once with only the later condition true, to prove that rule is
genuinely reachable. The remaining tests sit exactly on a limit and one hundredth
of a unit past it: a discharge-port accumulation landing precisely on the port's
ceiling, and a premium declaration whose variance lands precisely on the audit
tolerance.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CERTIFICATE_DECLARED_SHIPMENT,
    ERR_COMMODITY_SHARE_EXCEEDED,
    ERR_PACKAGING_WARRANTY_BREACH,
    ERR_PORT_ACCUMULATION_EXCEEDED,
    ERR_VESSEL_ACCUMULATION_EXCEEDED,
    ERR_VESSEL_BLOCKED,
    EXPECTED_INSURED_VALUE_CIF,
    EXPECTED_TOTAL_PREMIUM,
    PORT_NLRTM,
    UNDERWRITER,
    VESSEL_COMET,
    VESSEL_KITE,
    ApiClient,
    JsonDict,
    assert_money,
    assert_rate,
    assert_total_count,
    audit_declaration,
    build_canonical_environment,
    build_draft_certificate,
    build_issued_certificate,
    create_certificate,
    create_declaration,
    create_open_policy,
    create_vessel,
    declare_ga_event,
    issue_certificate,
    policy_version,
    read_certificate,
    read_declaration,
    read_policy,
    read_port,
    read_vessel,
    submit_declaration,
)

# War and strikes cover are switched off wherever premium is not the subject, so
# the only figures in play are insured values and the ledgers they move.
NO_WAR_OR_STRIKES = {"war_cover_requested": False, "strikes_cover_requested": False}

# A hull ceiling deliberately set below two canonical shipments: one 1155000.00
# certificate fits, a second takes the hull to 2310000.00 and does not.
LOW_VESSEL_ACCUMULATION_LIMIT = 1500000

# A discharge port whose ceiling is exactly two canonical shipments, so the
# second certificate lands on the limit to the cent.
PORT_LIMIT_FOR_TWO_SHIPMENTS = 2 * EXPECTED_INSURED_VALUE_CIF

# The smallest declarable value: one cent of extra exposure.
ONE_CENT = 0.01

# The commodity's share of a conveyance: 3000000.00 * 0.80, rounded to 2 decimals.
COMMODITY_SHARE_CEILING = 2400000.00
# One shipment over that ceiling, and one comfortably under it.
VALUE_OVER_SHARE_CEILING = 2500000
VALUE_UNDER_SHARE_CEILING = 1000000

# Against a computed premium of 6444.91, this reported total gives a variance of
# -161.12, which is 2.4999...% of the computed total and rounds to exactly 2.50.
DECLARED_AT_TOLERANCE = 6283.79
VARIANCE_AT_TOLERANCE = -161.12
VARIANCE_PCT_AT_TOLERANCE = 2.50

# Seventy-nine cents lower: a variance of -161.91, which is 2.5122...% and rounds
# to 2.51 — one hundredth of a point above the tolerance.
DECLARED_OVER_TOLERANCE = 6283.00
VARIANCE_OVER_TOLERANCE = -161.91
VARIANCE_PCT_OVER_TOLERANCE = 2.51


# ---------------------------------------------------------------------------
# Composite preconditions, built through the documented endpoints only
# ---------------------------------------------------------------------------
def _build_held_hull_and_control_hull(api: ApiClient) -> JsonDict:
    """
    One open cover, two green ports and two screened hulls that each carry a
    1500000.00 accumulation ceiling. Each hull already carries one issued
    1155000.00 certificate, so a second identical shipment would take either
    hull to 2310000.00. A general average is then declared on the first hull
    only, which puts that hull — and only that hull — under hold. Both second
    shipments are left in draft, ready to be issued by the tests.
    """
    env = build_canonical_environment(
        api,
        vessel={**VESSEL_KITE,
                "vessel_accumulation_limit_amount": LOW_VESSEL_ACCUMULATION_LIMIT},
    )
    control_hull = create_vessel(
        api, VESSEL_COMET,
        vessel_accumulation_limit_amount=LOW_VESSEL_ACCUMULATION_LIMIT)
    env["control_vessel"] = control_hull
    env["control_vessel_id"] = control_hull["id"]

    filler_on_held = build_draft_certificate(
        api, env, certificate_number="CERT-A", **NO_WAR_OR_STRIKES)
    candidate_on_held = build_draft_certificate(
        api, env, certificate_number="CERT-E", **NO_WAR_OR_STRIKES)
    filler_on_control = build_draft_certificate(
        api, env, certificate_number="CERT-F",
        vessel_id=control_hull["id"], **NO_WAR_OR_STRIKES)
    candidate_on_control = build_draft_certificate(
        api, env, certificate_number="CERT-G",
        vessel_id=control_hull["id"], **NO_WAR_OR_STRIKES)

    issue_certificate(api, filler_on_held["id"], env["policy_id"])
    issue_certificate(api, filler_on_control["id"], env["policy_id"])

    env["ga_event"] = declare_ga_event(api, env["vessel_id"])
    env["candidate_on_held_id"] = candidate_on_held["id"]
    env["candidate_on_control_id"] = candidate_on_control["id"]
    return env


def _issue(api: ApiClient, certificate_id: str, policy_id: str):
    """Attempt an issue against the open cover's current version."""
    return api.issue_certificate(
        certificate_id,
        {"expected_open_policy_version": policy_version(api, policy_id)},
        UNDERWRITER,
    )


def _declaration_payload(env: JsonDict, certificate_number: str,
                         packaging_code: str, declared_value: float) -> JsonDict:
    """A declared-value shipment payload with the packaging and value under test."""
    return {
        "open_policy_id": env["policy_id"],
        "commodity_class_id": env["commodity_class_id"],
        "vessel_id": env["vessel_id"],
        "loading_port_id": env["loading_port_id"],
        "discharge_port_id": env["discharge_port_id"],
        "certificate_number": certificate_number,
        "valuation_basis": "DECLARED_VALUE",
        "packaging_code": packaging_code,
        "package_count": 300,
        "gross_weight_kg": 42000,
        "sailing_date": "2026-08-10T00:00:00Z",
        "discharge_date": "2026-09-05T00:00:00Z",
        "declared_value": declared_value,
        "war_cover_requested": False,
        "strikes_cover_requested": False,
    }


def _build_discharge_port_at_its_ceiling(api: ApiClient) -> JsonDict:
    """
    A discharge port limited to exactly two canonical shipments, with the first
    of them already issued. Two further drafts wait: a second 1155000.00
    shipment that would fill the ledger to the limit exactly, and a one-cent
    shipment that would take it one cent over. All three discharge on the same
    date at the same port, so their storage windows overlap.
    """
    env = build_canonical_environment(
        api,
        discharge_port={
            **PORT_NLRTM,
            "port_accumulation_limit_amount": PORT_LIMIT_FOR_TWO_SHIPMENTS,
        },
    )
    first = build_draft_certificate(
        api, env, certificate_number="CERT-A", **NO_WAR_OR_STRIKES)
    at_the_limit = build_draft_certificate(
        api, env, certificate_number="CERT-H", **NO_WAR_OR_STRIKES)
    one_cent_over = build_draft_certificate(
        api, env, base=CERTIFICATE_DECLARED_SHIPMENT,
        certificate_number="CERT-I", declared_value=ONE_CENT,
        package_count=1, gross_weight_kg=10, **NO_WAR_OR_STRIKES)

    env["first_certificate"] = issue_certificate(
        api, first["id"], env["policy_id"])
    env["at_the_limit_id"] = at_the_limit["id"]
    env["one_cent_over_id"] = one_cent_over["id"]
    return env


def _build_two_reporting_periods(api: ApiClient) -> JsonDict:
    """
    Two active open covers on identical terms, each carrying one issued
    certificate of 6444.91 total premium and one open declaration over the month
    that certificate was issued in. The two covers keep the boundary legs apart:
    neither declaration can claim the other's certificate.
    """
    env = build_canonical_environment(
        api, policy_overrides={"policy_number": "OP-BND-1"})
    env["certificate_one"] = build_issued_certificate(
        api, env, certificate_number="CERT-B1")

    second_policy = create_open_policy(
        api, policy_number="OP-BND-2", assured_name="Comet Trading Pte")
    second_draft = create_certificate(
        api, second_policy["id"], env["commodity_class_id"], env["vessel_id"],
        env["loading_port_id"], env["discharge_port_id"],
        certificate_number="CERT-B2",
        sailing_date="2026-08-11T00:00:00Z",
        discharge_date="2026-09-06T00:00:00Z")
    env["second_policy"] = second_policy
    env["second_policy_id"] = second_policy["id"]
    env["certificate_two"] = issue_certificate(
        api, second_draft["id"], second_policy["id"])

    env["declaration_one_id"] = create_declaration(api, env["policy_id"])["id"]
    env["declaration_two_id"] = create_declaration(
        api, second_policy["id"])["id"]
    return env


# ---------------------------------------------------------------------------
# An uninsurable hull is refused before its accumulation is even measured
# ---------------------------------------------------------------------------
def test_hull_under_average_hold_is_refused_before_its_accumulation_is_measured(
        api: ApiClient) -> None:
    """
    A shipment on a hull that is both under general average hold and over its
    accumulation ceiling is refused for the hull, not for the money.

    Then the hull: the nominated vessel must be `APPROVED` or `OVERAGE_SURCHARGED`, and a vessel that is `BLOCKED`, still `PENDING_REVIEW` or in `GA_HOLD` gives `ERR_VESSEL_BLOCKED` (HTTP 422) — refused before any capacity arithmetic is attempted.

    Design: Difficulty/priority_pair_validation_conflict/vessel_state_beats_vessel_accumulation_at_issue
    """
    env = _build_held_hull_and_control_hull(api)

    held_hull = read_vessel(api, env["vessel_id"])
    assert held_hull["status"] == "GA_HOLD"
    assert_money(held_hull["accumulated_insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "held hull accumulated_insured_value")

    candidate = read_certificate(api, env["candidate_on_held_id"])
    assert_money(candidate["insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "candidate insured_value")
    assert (float(held_hull["accumulated_insured_value"])
            + float(candidate["insured_value"])
            > LOW_VESSEL_ACCUMULATION_LIMIT), (
        "the candidate must also breach the hull's accumulation ceiling"
    )

    response = _issue(api, env["candidate_on_held_id"], env["policy_id"])
    validate_error(response, ERR_VESSEL_BLOCKED)


def test_same_accumulation_breach_on_an_insurable_hull_reports_the_hull_ledger(
        api: ApiClient) -> None:
    """
    The identical accumulation breach on a hull that is not held reports the
    single-vessel accumulation error, so the fiscal rule is genuinely reachable.

    The system sums the `amount` of every accumulation ledger row of scope `VESSEL` on this vessel whose `status` is `ACTIVE`, and the sum plus this insured value must not exceed the vessel's `vessel_accumulation_limit_amount`.

    Design: Difficulty/priority_pair_validation_conflict/vessel_state_beats_vessel_accumulation_at_issue
    """
    env = _build_held_hull_and_control_hull(api)

    control_hull = read_vessel(api, env["control_vessel_id"])
    assert control_hull["status"] == "APPROVED"
    assert_money(control_hull["accumulated_insured_value"],
                 EXPECTED_INSURED_VALUE_CIF,
                 "control hull accumulated_insured_value")

    response = _issue(api, env["candidate_on_control_id"], env["policy_id"])
    validate_error(response, ERR_VESSEL_ACCUMULATION_EXCEEDED)

    assert_money(read_vessel(api, env["control_vessel_id"])
                 ["accumulated_insured_value"],
                 EXPECTED_INSURED_VALUE_CIF,
                 "control hull accumulated_insured_value after refusal")


def test_neither_refused_issue_leaves_a_draft_certificate_or_a_booked_exposure(
        api: ApiClient) -> None:
    """
    Both refusals leave their certificates in draft and book nothing on the open
    cover: only the two successful issues stand on its aggregate.

    No certificate may be issued on a hull in `GA_HOLD`.

    Design: Difficulty/priority_pair_validation_conflict/vessel_state_beats_vessel_accumulation_at_issue
    """
    env = _build_held_hull_and_control_hull(api)

    validate_error(_issue(api, env["candidate_on_held_id"], env["policy_id"]),
                   ERR_VESSEL_BLOCKED)
    validate_error(_issue(api, env["candidate_on_control_id"], env["policy_id"]),
                   ERR_VESSEL_ACCUMULATION_EXCEEDED)

    assert read_certificate(api, env["candidate_on_held_id"])["status"] == "DRAFT"
    assert read_certificate(api, env["candidate_on_control_id"])["status"] == "DRAFT"

    policy = read_policy(api, env["policy_id"])
    assert_money(policy["aggregate_insured_value_booked"],
                 2 * EXPECTED_INSURED_VALUE_CIF,
                 "aggregate_insured_value_booked")
    assert policy["certificates_issued_count"] == 2


# ---------------------------------------------------------------------------
# The packaging warranty is tested before any commercial ceiling
# ---------------------------------------------------------------------------
def test_packaging_warranty_beats_the_commodity_share_ceiling_on_declaration(
        api: ApiClient, canonical_env: JsonDict) -> None:
    """
    A declaration that both declares the wrong packaging and asks for more than
    its commodity's share of the conveyance is refused for the packaging.

    Third — before any commercial consideration whatsoever — the packaging warranty: the declared `packaging_code` must equal the commodity class's `required_packaging_code`, and a mismatch is `ERR_PACKAGING_WARRANTY_BREACH` (HTTP 422).

    Design: Difficulty/priority_pair_validation_conflict/packaging_warranty_beats_commodity_share_at_certificate_creation
    """
    assert canonical_env["commodity_class"]["required_packaging_code"] == "EXPORT_CRATE"
    assert_money(canonical_env["policy"]["conveyance_limit_amount"], 3000000,
                 "conveyance_limit_amount")
    assert VALUE_OVER_SHARE_CEILING > COMMODITY_SHARE_CEILING, (
        "the declared value must also breach the commodity share ceiling"
    )

    response = api.create_certificate(
        _declaration_payload(canonical_env, "CERT-DUAL", "STD",
                             VALUE_OVER_SHARE_CEILING),
        canonical_env["assured"])
    validate_error(response, ERR_PACKAGING_WARRANTY_BREACH)


def test_commodity_share_ceiling_is_reachable_once_the_packaging_matches(
        api: ApiClient, canonical_env: JsonDict) -> None:
    """
    With the warranty honoured, the same oversized declaration is refused for the
    commodity's share of the conveyance instead.

    The insured value must not exceed the policy's `conveyance_limit_amount` multiplied by the commodity class's `max_conveyance_share_pct`, that product being rounded half up to 2 decimals before the comparison.

    Design: Difficulty/priority_pair_validation_conflict/packaging_warranty_beats_commodity_share_at_certificate_creation
    """
    share_pct = float(canonical_env["commodity_class"]["max_conveyance_share_pct"])
    conveyance_limit = float(canonical_env["policy"]["conveyance_limit_amount"])
    assert_money(round(conveyance_limit * share_pct, 2), COMMODITY_SHARE_CEILING,
                 "commodity share ceiling")

    response = api.create_certificate(
        _declaration_payload(canonical_env, "CERT-SHARE", "EXPORT_CRATE",
                             VALUE_OVER_SHARE_CEILING),
        canonical_env["assured"])
    validate_error(response, ERR_COMMODITY_SHARE_EXCEEDED)


def test_packaging_breach_alone_refuses_and_no_declaration_survives(
        api: ApiClient, canonical_env: JsonDict) -> None:
    """
    Wrong packaging on a comfortably sized shipment still reports the warranty, and
    none of the three rejected declarations leaves a certificate behind.

    Packaging is a condition of cover, so it is checked ahead of every commercial constraint.

    Design: Difficulty/priority_pair_validation_conflict/packaging_warranty_beats_commodity_share_at_certificate_creation
    """
    assert VALUE_UNDER_SHARE_CEILING < COMMODITY_SHARE_CEILING, (
        "this leg must satisfy the commodity share ceiling"
    )

    validate_error(
        api.create_certificate(
            _declaration_payload(canonical_env, "CERT-PKG", "STD",
                                 VALUE_UNDER_SHARE_CEILING),
            canonical_env["assured"]),
        ERR_PACKAGING_WARRANTY_BREACH)
    validate_error(
        api.create_certificate(
            _declaration_payload(canonical_env, "CERT-DUAL", "STD",
                                 VALUE_OVER_SHARE_CEILING),
            canonical_env["assured"]),
        ERR_PACKAGING_WARRANTY_BREACH)
    validate_error(
        api.create_certificate(
            _declaration_payload(canonical_env, "CERT-SHARE", "EXPORT_CRATE",
                                 VALUE_OVER_SHARE_CEILING),
            canonical_env["assured"]),
        ERR_COMMODITY_SHARE_EXCEEDED)

    assert_total_count(
        api.list_certificates(UNDERWRITER,
                              {"open_policy_id": canonical_env["policy_id"]}),
        0, "certificates of the open cover")


# ---------------------------------------------------------------------------
# The discharge-port ceiling: exactly on it, and one cent past it
# ---------------------------------------------------------------------------
def test_discharge_port_exposure_landing_exactly_on_the_ceiling_is_accepted(
        api: ApiClient) -> None:
    """
    A second shipment that fills the discharge port's ledger to precisely its
    ceiling is issued, and the ledger reads the ceiling to the cent.

    Every comparison is strictly greater than: an exposure exactly equal to its limit is accepted, and one cent over it is rejected.

    Design: Difficulty/boundary_precision_check/port_accumulation_exact_limit_accepted_one_cent_over_rejected
    """
    env = _build_discharge_port_at_its_ceiling(api)

    port_before = read_port(api, env["discharge_port_id"])
    assert_money(port_before["port_accumulation_limit_amount"],
                 PORT_LIMIT_FOR_TWO_SHIPMENTS, "port_accumulation_limit_amount")
    assert_money(port_before["accumulated_insured_value"],
                 EXPECTED_INSURED_VALUE_CIF, "accumulated_insured_value")

    issued = validate_success(
        _issue(api, env["at_the_limit_id"], env["policy_id"]))
    assert issued["status"] == "ISSUED"
    assert_money(issued["insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "insured_value")

    port_after = read_port(api, env["discharge_port_id"])
    assert_money(port_after["accumulated_insured_value"],
                 PORT_LIMIT_FOR_TWO_SHIPMENTS,
                 "accumulated_insured_value at the ceiling")


def test_one_cent_over_the_discharge_port_ceiling_is_rejected(
        api: ApiClient) -> None:
    """
    With the ledger sitting exactly on the ceiling, a shipment worth a single cent
    takes it one cent over and is refused.

    The sum plus this insured value must not exceed the discharge port's `port_accumulation_limit_amount`; a breach is `ERR_PORT_ACCUMULATION_EXCEEDED` (HTTP 422).

    Design: Difficulty/boundary_precision_check/port_accumulation_exact_limit_accepted_one_cent_over_rejected
    """
    env = _build_discharge_port_at_its_ceiling(api)
    validate_success(_issue(api, env["at_the_limit_id"], env["policy_id"]))

    candidate = read_certificate(api, env["one_cent_over_id"])
    assert_money(candidate["insured_value"], ONE_CENT, "one-cent insured_value")

    response = _issue(api, env["one_cent_over_id"], env["policy_id"])
    validate_error(response, ERR_PORT_ACCUMULATION_EXCEEDED)

    refused = read_certificate(api, env["one_cent_over_id"])
    assert refused["status"] == "DRAFT"
    assert_money(refused["insured_value"], ONE_CENT,
                 "one-cent insured_value after refusal")


def test_refused_one_cent_shipment_books_no_partial_exposure_at_the_port(
        api: ApiClient) -> None:
    """
    The refusal writes nothing: the port ledger still reads its ceiling and only
    the two accepted shipments occupy the storage window.

    The system sums the `amount` of every accumulation ledger row of scope `DISCHARGE_PORT` on this certificate's `discharge_port_id` whose `status` is `ACTIVE` and whose own window overlaps the candidate's — meaning the existing row's `window_start_at` is strictly earlier than the candidate's end and the existing row's `window_end_at` is strictly later than the candidate's start.

    Design: Difficulty/boundary_precision_check/port_accumulation_exact_limit_accepted_one_cent_over_rejected
    """
    env = _build_discharge_port_at_its_ceiling(api)
    validate_success(_issue(api, env["at_the_limit_id"], env["policy_id"]))
    validate_error(_issue(api, env["one_cent_over_id"], env["policy_id"]),
                   ERR_PORT_ACCUMULATION_EXCEEDED)

    assert_money(read_port(api, env["discharge_port_id"])
                 ["accumulated_insured_value"],
                 PORT_LIMIT_FOR_TWO_SHIPMENTS,
                 "accumulated_insured_value after the refusal")

    rows = assert_total_count(
        api.list_accumulation_entries(
            UNDERWRITER,
            {"port_id": env["discharge_port_id"],
             "scope_type": "DISCHARGE_PORT"}),
        2, "discharge-port accumulation entries")
    for row in rows:
        assert row["status"] == "ACTIVE"
        assert_money(row["amount"], EXPECTED_INSURED_VALUE_CIF,
                     "accumulation entry amount")


# ---------------------------------------------------------------------------
# The audit tolerance: exactly on it, and one hundredth of a point past it
# ---------------------------------------------------------------------------
def test_variance_exactly_at_the_audit_tolerance_finishes_accepted(
        api: ApiClient) -> None:
    """
    A reported total 161.12 under a computed 6444.91 is a variance of exactly 2.50
    percent, which sits on the tolerance and closes the audit as accepted.

    When the variance percentage is at or under the tolerance of 2.5 percent, the declaration goes `UNDER_AUDIT → ACCEPTED`, `audit_adjustment_amount` is set to 0.00, and the parent policy's `status` is not touched.

    Design: Difficulty/boundary_precision_check/declaration_variance_exactly_at_audit_tolerance_is_accepted
    """
    env = _build_two_reporting_periods(api)

    submitted = submit_declaration(api, env["declaration_one_id"],
                                   env["policy_id"], DECLARED_AT_TOLERANCE)
    assert submitted["certificate_count"] == 1
    assert_money(submitted["computed_premium_total"], EXPECTED_TOTAL_PREMIUM,
                 "computed_premium_total")
    assert_money(submitted["variance_amount"], VARIANCE_AT_TOLERANCE,
                 "variance_amount")
    assert_rate(submitted["variance_pct"], VARIANCE_PCT_AT_TOLERANCE, places=2,
                label="variance_pct")

    finished = audit_declaration(api, env["declaration_one_id"],
                                "variance exactly at tolerance")
    assert finished["status"] == "ACCEPTED"
    assert_money(finished["audit_adjustment_amount"], 0.00,
                 "audit_adjustment_amount")
    assert read_policy(api, env["policy_id"])["status"] == "ACTIVE"


def test_variance_one_hundredth_of_a_point_over_the_tolerance_finishes_adjusted(
        api: ApiClient) -> None:
    """
    Seventy-nine cents lower takes the variance to 2.51 percent, and the audit
    closes as adjusted for the absolute variance of 161.91.

    When the variance percentage is strictly above 2.5 percent, the declaration goes `UNDER_AUDIT → ADJUSTED` and `audit_adjustment_amount` is set to the absolute value of `variance_amount` — the adjustment is booked on the declaration only, and the policy's `aggregate_premium_booked` is deliberately *not* touched by it.

    Design: Difficulty/boundary_precision_check/declaration_variance_exactly_at_audit_tolerance_is_accepted
    """
    env = _build_two_reporting_periods(api)

    submitted = submit_declaration(api, env["declaration_two_id"],
                                   env["second_policy_id"],
                                   DECLARED_OVER_TOLERANCE)
    assert_money(submitted["computed_premium_total"], EXPECTED_TOTAL_PREMIUM,
                 "computed_premium_total")
    assert_money(submitted["variance_amount"], VARIANCE_OVER_TOLERANCE,
                 "variance_amount")
    assert_rate(submitted["variance_pct"], VARIANCE_PCT_OVER_TOLERANCE, places=2,
                label="variance_pct")

    finished = audit_declaration(api, env["declaration_two_id"],
                                "variance one hundredth over tolerance")
    assert finished["status"] == "ADJUSTED"
    assert_money(finished["audit_adjustment_amount"],
                 abs(VARIANCE_OVER_TOLERANCE), "audit_adjustment_amount")
    assert_money(read_policy(api, env["second_policy_id"])
                 ["aggregate_premium_booked"], EXPECTED_TOTAL_PREMIUM,
                 "aggregate_premium_booked")


def test_an_adjusted_variance_under_the_suspension_threshold_leaves_both_covers_active(
        api: ApiClient) -> None:
    """
    Both boundary legs stay well under four times the tolerance, so neither open
    cover is suspended and each declaration lands in its own outcome.

    That branch carries one further conditional consequence: when the variance percentage is strictly above 10.0 percent, four times the audit tolerance, the parent policy moves `ACTIVE → SUSPENDED`, its `version` increments, and no new certificate may be declared or issued under it until the position is corrected.

    Design: Difficulty/boundary_precision_check/declaration_variance_exactly_at_audit_tolerance_is_accepted
    """
    env = _build_two_reporting_periods(api)

    submit_declaration(api, env["declaration_one_id"], env["policy_id"],
                       DECLARED_AT_TOLERANCE)
    audit_declaration(api, env["declaration_one_id"],
                      "variance exactly at tolerance")
    submit_declaration(api, env["declaration_two_id"], env["second_policy_id"],
                       DECLARED_OVER_TOLERANCE)
    audit_declaration(api, env["declaration_two_id"],
                      "variance one hundredth over tolerance")

    assert read_policy(api, env["policy_id"])["status"] == "ACTIVE"
    assert read_policy(api, env["second_policy_id"])["status"] == "ACTIVE"

    accepted = read_declaration(api, env["declaration_one_id"], UNDERWRITER)
    adjusted = read_declaration(api, env["declaration_two_id"], UNDERWRITER)
    assert accepted["status"] == "ACCEPTED"
    assert adjusted["status"] == "ADJUSTED"
    assert_money(accepted["audit_adjustment_amount"], 0.00,
                 "accepted audit_adjustment_amount")
    assert_money(adjusted["audit_adjustment_amount"],
                 abs(VARIANCE_OVER_TOLERANCE), "adjusted audit_adjustment_amount")
