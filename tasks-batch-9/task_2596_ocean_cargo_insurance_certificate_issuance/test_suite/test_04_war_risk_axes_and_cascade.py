"""
War and strikes cover: the two cover axes of a certificate, and the cascade a
port listing fires.

Covers the political-risk axis moving on its own triggers while the transit axis
stands still — a listing terminating war cover, a reinstatement buying it back
at a new rate, and a confirmed delivery ending transit afterwards — and the
chain of consequences a listing sets off across the open cover, its exposed and
unexposed certificates, the return-premium ledger and a premium report that is
already under way.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CERTIFICATE_DECLARED_SHIPMENT,
    COMPLIANCE_OFFICER,
    PORT_USNYC,
    UNDERWRITER,
    ApiClient,
    JsonDict,
    assert_money,
    assert_rate,
    build_canonical_environment,
    build_draft_certificate,
    build_issued_certificate,
    create_declaration,
    create_port,
    make_assured_headers,
    read_certificate,
    read_declaration,
    read_policy,
    read_port,
    read_vessel,
    set_clock,
    submit_declaration,
)

# The exposed certificate: insured 1155000.00, war 693.00, strikes 294.53 and a
# total premium of 6444.91.
EXPECTED_INSURED_VALUE = 1155000.00
EXPECTED_WAR_PLUS_STRIKES_RETURN = 987.53

# Reinstated war cover is never free: 1155000.00 / 1000 x 0.400 = 462.00.
REINSTATEMENT_RATE = 0.400
EXPECTED_REINSTATEMENT_PREMIUM = 462.00

# The delivery the assured confirms, five days after the 2026-08-10 attachment.
DELIVERY_INSTANT = "2026-08-15T00:00:00Z"

# The control interest: 400000.00 declared through a port that is never listed.
# 400.00 x 4.7250 = 1890.00, 400.00 x 0.6000 = 240.00, 400.00 x 0.255 = 102.00.
CONTROL_DECLARED_VALUE = 400000
EXPECTED_CONTROL_TOTAL_PREMIUM = 2232.00

# The reporting period both certificates were issued inside.
PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"

# 6444.91 + 2232.00 reported exactly, then 5457.38 + 2232.00 after the return.
EXPECTED_COMPUTED_BEFORE = 8676.91
EXPECTED_COMPUTED_AFTER = 7689.38
EXPECTED_VARIANCE_AMOUNT = 987.53
# 987.53 / 7689.38 x 100 = 12.844..., rounded half up to 2 decimals.
EXPECTED_VARIANCE_PCT = 12.84


def _list_discharge_port(api: ApiClient, env: JsonDict) -> JsonDict:
    """The war-risk committee designates the discharge port a listed area."""
    return validate_success(api.set_port_war_risk_tier(
        env["discharge_port_id"], {"war_risk_tier": "LISTED_AREA"},
        COMPLIANCE_OFFICER))


def _reinstate_war_cover(api: ApiClient, env: JsonDict) -> JsonDict:
    """Bring the listed port back down to amber, then buy the cover back."""
    validate_success(api.set_port_war_risk_tier(
        env["discharge_port_id"], {"war_risk_tier": "AMBER"},
        COMPLIANCE_OFFICER))
    return validate_success(api.reinstate_war_cover(
        env["policy_id"], {"reinstatement_rate_per_mille": REINSTATEMENT_RATE},
        COMPLIANCE_OFFICER))


def _confirm_delivery(api: ApiClient, env: JsonDict) -> JsonDict:
    """Move the clock to the delivery date and confirm final delivery."""
    set_clock(api, DELIVERY_INSTANT)
    return validate_success(api.confirm_delivery(
        env["certificate_id"], make_assured_headers(env["policy_id"]),
        {"delivered_at": DELIVERY_INSTANT}))


def _build_cascade_environment(api: ApiClient) -> JsonDict:
    """
    One open cover carrying two issued certificates — the exposed one discharging
    at the port about to be listed, the control one discharging elsewhere — with a
    premium report over the month they were both issued in already submitted at
    exactly the computed figure of 8676.91.
    """
    env = build_canonical_environment(api)
    env["control_port"] = create_port(api, PORT_USNYC)
    env["certificate"] = build_issued_certificate(api, env)
    env["certificate_id"] = env["certificate"]["id"]
    env["control_certificate"] = build_issued_certificate(
        api, env,
        base=CERTIFICATE_DECLARED_SHIPMENT,
        certificate_number="CERT-CTL",
        declared_value=CONTROL_DECLARED_VALUE,
        package_count=40,
        gross_weight_kg=6000,
        sailing_date="2026-08-12T00:00:00Z",
        discharge_date="2026-09-10T00:00:00Z",
        discharge_port_id=env["control_port"]["id"],
    )
    env["control_certificate_id"] = env["control_certificate"]["id"]
    declaration = create_declaration(api, env["policy_id"], PERIOD_START, PERIOD_END)
    env["declaration_id"] = declaration["id"]
    env["declaration"] = submit_declaration(
        api, env["declaration_id"], env["policy_id"], EXPECTED_COMPUTED_BEFORE)
    return env


def test_listing_a_port_terminates_the_war_axis_and_leaves_transit_running(
        api: ApiClient, issued_certificate_env: JsonDict) -> None:
    """
    The exposed certificate loses its war cover the moment its discharge port is
    listed, gets war plus strikes back, and is still an issued, running risk.

    A certificate whose `status` is `ISSUED`, whose `war_cover_status` is `ATTACHED` or `REINSTATED`, and whose `loading_port_id` or `discharge_port_id` is the newly listed port moves its war axis to `TERMINATED`, and premium comes back.

    Design: Difficulty/non_linear_state_machine/certificate_transit_and_war_axes_advance_independently
    """
    before = read_certificate(api, issued_certificate_env["certificate_id"])
    assert before["status"] == "ISSUED"
    assert before["war_cover_status"] == "ATTACHED"

    _list_discharge_port(api, issued_certificate_env)

    certificate = read_certificate(api, issued_certificate_env["certificate_id"])
    assert certificate["war_cover_status"] == "TERMINATED"
    assert certificate["status"] == "ISSUED"
    assert_money(certificate["return_premium_amount"],
                 EXPECTED_WAR_PLUS_STRIKES_RETURN, "return_premium_amount")


def test_reinstating_war_cover_charges_the_certificate_without_moving_transit(
        api: ApiClient, issued_certificate_env: JsonDict) -> None:
    """
    Once the port is back to amber the war axis is bought back at 0.400 per mille
    for 462.00, while the transit axis stays exactly where it was.

    Every certificate on the policy whose `status` is `ISSUED` and whose `war_cover_status` is `TERMINATED` is examined; if neither its loading port nor its discharge port is in tier `LISTED_AREA` at that instant, its war axis moves `TERMINATED → REINSTATED` and it is charged additional premium: its `reinstatement_premium_amount` is set to its insured value divided by 1000, multiplied by the policy's newly agreed reinstatement rate per mille, rounded half up to 2 decimals.

    Design: Difficulty/non_linear_state_machine/certificate_transit_and_war_axes_advance_independently
    """
    _list_discharge_port(api, issued_certificate_env)
    _reinstate_war_cover(api, issued_certificate_env)

    certificate = read_certificate(api, issued_certificate_env["certificate_id"])
    assert certificate["war_cover_status"] == "REINSTATED"
    assert certificate["status"] == "ISSUED"
    assert_money(certificate["insured_value"], EXPECTED_INSURED_VALUE,
                 "insured_value")
    assert_money(certificate["reinstatement_premium_amount"],
                 EXPECTED_REINSTATEMENT_PREMIUM, "reinstatement_premium_amount")


def test_reinstatement_clears_the_termination_record_on_the_open_cover(
        api: ApiClient, issued_certificate_env: JsonDict) -> None:
    """
    The cover's own war axis comes back to reinstated at the newly agreed rate and
    forgets which port terminated it, while its contractual status never moves off
    active.

    On success the policy's war axis moves `TERMINATED → REINSTATED`, the supplied rate is stored in `reinstatement_rate_per_mille`, and both `war_terminated_at` and `war_termination_port_unlocode` are cleared to null.

    Design: Difficulty/non_linear_state_machine/certificate_transit_and_war_axes_advance_independently
    """
    _list_discharge_port(api, issued_certificate_env)
    terminated = read_policy(api, issued_certificate_env["policy_id"])
    assert terminated["war_cover_status"] == "TERMINATED"

    _reinstate_war_cover(api, issued_certificate_env)

    policy = read_policy(api, issued_certificate_env["policy_id"])
    assert policy["war_cover_status"] == "REINSTATED"
    assert policy["status"] == "ACTIVE"
    assert_rate(policy["reinstatement_rate_per_mille"], REINSTATEMENT_RATE,
                places=3, label="reinstatement_rate_per_mille")
    assert policy["war_terminated_at"] is None
    assert policy["war_termination_port_unlocode"] is None


def test_confirmed_delivery_ends_transit_while_the_war_axis_stays_reinstated(
        api: ApiClient, issued_certificate_env: JsonDict) -> None:
    """
    The combined state of an ended transit and a reinstated war cover is reachable
    on one row: the two axes answer to different triggers.

    A policy has a contractual `status` and, quite separately, a `war_cover_status`; a certificate likewise carries `status` for its own lifecycle and `war_cover_status` for the war and strikes cover bought on it; a claim file carries `status` for the adjustment lifecycle and `subrogation_status` for the recovery action against the carrier.

    Design: Difficulty/non_linear_state_machine/certificate_transit_and_war_axes_advance_independently
    """
    _list_discharge_port(api, issued_certificate_env)
    _reinstate_war_cover(api, issued_certificate_env)
    delivered = _confirm_delivery(api, issued_certificate_env)

    assert delivered["status"] == "TRANSIT_ENDED"
    assert delivered["war_cover_status"] == "REINSTATED"

    certificate = read_certificate(api, issued_certificate_env["certificate_id"])
    assert certificate["status"] == "TRANSIT_ENDED"
    assert certificate["war_cover_status"] == "REINSTATED"
    assert_money(certificate["return_premium_amount"],
                 EXPECTED_WAR_PLUS_STRIKES_RETURN, "return_premium_amount")
    assert_money(certificate["reinstatement_premium_amount"],
                 EXPECTED_REINSTATEMENT_PREMIUM, "reinstatement_premium_amount")


def test_ending_transit_releases_the_vessel_and_port_accumulation(
        api: ApiClient, issued_certificate_env: JsonDict) -> None:
    """
    Confirming delivery releases all three exposure rows for the delivery reason
    and empties the hull's and both ports' accumulation ledgers.

    The certificate moves to `TRANSIT_ENDED`, its `ACTIVE` accumulation rows become `RELEASED` with `release_reason` `DELIVERY_CONFIRMED`, both ledgers fall, and the certificate's `version` increments.

    Design: Difficulty/non_linear_state_machine/certificate_transit_and_war_axes_advance_independently
    """
    _list_discharge_port(api, issued_certificate_env)
    _reinstate_war_cover(api, issued_certificate_env)
    _confirm_delivery(api, issued_certificate_env)

    rows, meta = validate_paginated(api.list_accumulation_entries(
        UNDERWRITER, {"certificate_id": issued_certificate_env["certificate_id"]}))
    assert meta["total_count"] == 3
    for row in rows:
        assert row["status"] == "RELEASED"
        assert row["release_reason"] == "DELIVERY_CONFIRMED"

    assert_money(read_vessel(api, issued_certificate_env["vessel_id"])[
        "accumulated_insured_value"], 0.00, "vessel accumulated_insured_value")
    assert_money(read_port(api, issued_certificate_env["discharge_port_id"])[
        "accumulated_insured_value"], 0.00,
        "discharge port accumulated_insured_value")
    assert_money(read_port(api, issued_certificate_env["loading_port_id"])[
        "accumulated_insured_value"], 0.00,
        "loading port accumulated_insured_value")


def test_the_listing_sets_the_tier_and_zeroes_the_war_rate_multiplier(
        api: ApiClient) -> None:
    """
    A port designated a listed area carries a multiplier of 0.0, so no war cover
    is obtainable there at any price.

    Re-tiering always updates the port's `war_risk_tier` and its derived `war_rate_multiplier` (1.0 for `GREEN`, 1.5 for `AMBER`, 0.0 for `LISTED_AREA`) and increments the port's `version`.

    Design: Difficulty/transitive_cascade/listed_area_war_termination_four_link_cascade
    """
    env = _build_cascade_environment(api)
    before = read_port(api, env["discharge_port_id"])
    assert before["war_risk_tier"] == "GREEN"

    listed = _list_discharge_port(api, env)

    assert listed["war_risk_tier"] == "LISTED_AREA"
    assert_rate(listed["war_rate_multiplier"], 0.0, places=2,
                label="war_rate_multiplier")
    assert listed["version"] == before["version"] + 1
    assert read_port(api, env["discharge_port_id"])["war_risk_tier"] == "LISTED_AREA"


def test_the_exposed_open_cover_terminates_and_records_the_listed_port(
        api: ApiClient) -> None:
    """
    Because a listed port now sits on an issued certificate of this cover, the
    cover's war axis terminates and the bare code of the listed port is kept for
    the audit trail.

    On each such policy the system records `war_terminated_at` as the logical clock instant and `war_termination_port_unlocode` as the listed port's `unlocode` — a bare code string kept for the audit trail rather than a reference to the port row — and increments the policy's `version`.

    Design: Difficulty/transitive_cascade/listed_area_war_termination_four_link_cascade
    """
    env = _build_cascade_environment(api)
    assert read_policy(api, env["policy_id"])["war_cover_status"] == "ATTACHED"

    _list_discharge_port(api, env)

    policy = read_policy(api, env["policy_id"])
    assert policy["war_cover_status"] == "TERMINATED"
    assert policy["war_termination_port_unlocode"] == "NLRTM"
    assert is_iso8601_timestamp(policy["war_terminated_at"]), (
        f"war_terminated_at is not ISO 8601: {policy['war_terminated_at']!r}"
    )


def test_the_exposed_certificate_returns_war_and_strikes_in_full(
        api: ApiClient) -> None:
    """
    Because the cover's war axis terminated in this request, the exposed
    certificate's own axis terminates and both political components come back:
    693.00 plus 294.53.

    A certificate coming from `ATTACHED` has its `return_premium_amount` increased by its `war_premium_amount` plus its `strikes_premium_amount` — both components return in full, because both were sold against a geography that no longer exists.

    Design: Difficulty/transitive_cascade/listed_area_war_termination_four_link_cascade
    """
    env = _build_cascade_environment(api)

    _list_discharge_port(api, env)

    certificate = read_certificate(api, env["certificate_id"])
    assert certificate["war_cover_status"] == "TERMINATED"
    assert certificate["status"] == "ISSUED"
    assert_money(
        float(certificate["war_premium_amount"])
        + float(certificate["strikes_premium_amount"]),
        EXPECTED_WAR_PLUS_STRIKES_RETURN,
        "war plus strikes premium")
    assert_money(certificate["return_premium_amount"],
                 EXPECTED_WAR_PLUS_STRIKES_RETURN, "return_premium_amount")


def test_a_certificate_away_from_the_listed_port_is_left_entirely_untouched(
        api: ApiClient) -> None:
    """
    The control interest shares the cover but discharges elsewhere, so it keeps
    its attached war cover, returns nothing, and is not even re-versioned.

    A certificate whose `status` is `ISSUED`, whose `war_cover_status` is `ATTACHED` or `REINSTATED`, and whose `loading_port_id` or `discharge_port_id` is the newly listed port moves its war axis to `TERMINATED`, and premium comes back.

    Design: Difficulty/transitive_cascade/listed_area_war_termination_four_link_cascade
    """
    env = _build_cascade_environment(api)
    before = read_certificate(api, env["control_certificate_id"])
    assert before["war_cover_status"] == "ATTACHED"

    _list_discharge_port(api, env)

    control = read_certificate(api, env["control_certificate_id"])
    assert control["war_cover_status"] == "ATTACHED"
    assert control["status"] == "ISSUED"
    assert_money(control["return_premium_amount"], 0.00,
                 "control return_premium_amount")
    assert_money(control["total_premium_amount"], EXPECTED_CONTROL_TOTAL_PREMIUM,
                 "control total_premium_amount")
    assert control["version"] == before["version"]


def test_the_open_cover_return_ledger_rises_by_the_booked_return(
        api: ApiClient) -> None:
    """
    Because a certificate booked a return, the cover's return-premium ledger rises
    to 987.53, while its written-premium ledger keeps the 8676.91 it booked at
    issue.

    The fourth link is fiscal: the policy's `aggregate_return_premium` rises by the sum of the returns booked on its certificates in the third link.

    Design: Difficulty/transitive_cascade/listed_area_war_termination_four_link_cascade
    """
    env = _build_cascade_environment(api)
    before = read_policy(api, env["policy_id"])
    assert_money(before["aggregate_return_premium"], 0.00,
                 "aggregate_return_premium before the listing")

    _list_discharge_port(api, env)

    policy = read_policy(api, env["policy_id"])
    assert_money(policy["aggregate_return_premium"],
                 EXPECTED_WAR_PLUS_STRIKES_RETURN, "aggregate_return_premium")
    assert_money(policy["aggregate_premium_booked"], EXPECTED_COMPUTED_BEFORE,
                 "aggregate_premium_booked")


def test_a_submitted_premium_report_is_reconciled_again_by_the_cascade(
        api: ApiClient) -> None:
    """
    The report was submitted at exactly the 8676.91 then computed; once the
    exposed certificate returns 987.53 the computed total falls to 7689.38 and the
    same report is suddenly 12.84 percent out.

    The fifth link is conditional and reaches into premium reporting: when an affected certificate has a `premium_declaration_id` and that declaration's `status` is `SUBMITTED` or `UNDER_AUDIT`, the declaration's `computed_premium_total`, `variance_amount` and `variance_pct` are recomputed on the spot, because the premium the insurer now believes it earned has changed under an audit that is already running.

    Design: Difficulty/transitive_cascade/listed_area_war_termination_four_link_cascade
    """
    env = _build_cascade_environment(api)
    submitted = env["declaration"]
    assert submitted["status"] == "SUBMITTED"
    assert submitted["certificate_count"] == 2
    assert_money(submitted["computed_premium_total"], EXPECTED_COMPUTED_BEFORE,
                 "computed_premium_total before the listing")
    assert_money(submitted["variance_amount"], 0.00,
                 "variance_amount before the listing")
    assert_rate(submitted["variance_pct"], 0.00, places=2,
                label="variance_pct before the listing")

    _list_discharge_port(api, env)

    declaration = read_declaration(api, env["declaration_id"], UNDERWRITER)
    assert_money(declaration["computed_premium_total"], EXPECTED_COMPUTED_AFTER,
                 "computed_premium_total")
    assert_money(declaration["variance_amount"], EXPECTED_VARIANCE_AMOUNT,
                 "variance_amount")
    assert_rate(declaration["variance_pct"], EXPECTED_VARIANCE_PCT, places=2,
                label="variance_pct")
    assert declaration["status"] == "SUBMITTED"


def test_the_cascade_leaves_the_cover_active_and_still_accepting_declarations(
        api: ApiClient) -> None:
    """
    Only the war axis moved: the cover is still active after the listing and a
    fresh shipment can still be declared under it.

    Note that this touches only the war axis: the policy's contractual `status` is unaffected and it keeps accepting declarations.

    Design: Difficulty/transitive_cascade/listed_area_war_termination_four_link_cascade
    """
    env = _build_cascade_environment(api)

    _list_discharge_port(api, env)

    policy = read_policy(api, env["policy_id"])
    assert policy["status"] == "ACTIVE"
    assert policy["war_cover_status"] == "TERMINATED"

    declared = build_draft_certificate(
        api, env, certificate_number="CERT-N", war_cover_requested=False,
        strikes_cover_requested=False)
    assert declared["status"] == "DRAFT"
    assert declared["open_policy_id"] == env["policy_id"]
