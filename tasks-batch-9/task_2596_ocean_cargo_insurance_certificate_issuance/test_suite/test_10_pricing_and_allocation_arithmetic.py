"""
Pricing, allocation and reconciliation arithmetic.

Covers the freight switch on the insured-value base, the worse-port war rate,
the classification and age screen's four age breakpoints, the three competing
clocks that pin the end of transit, the residual-cent waterfall that allocates
general average contributions, the certificate membership of a reporting
period, the pinned convention for a zero computed base, and a loss that lands
below the pinned excess.
"""

from datetime import datetime

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import (
    ADJUSTER_USER_ID,
    CERTIFICATE_CIF_SHIPMENT,
    CERTIFICATE_DECLARED_SHIPMENT,
    CLAIMS_ADJUSTER,
    CLAIMS_ADJUSTER_2,
    DEFAULT_CLOCK,
    PORT_NLRTM,
    PORT_SGSIN,
    PREMIUM_AUDITOR,
    UNDERWRITER,
    ApiClient,
    JsonDict,
    adjust_claim_file,
    assert_amounts,
    assert_common_fields,
    assert_money,
    assert_rate,
    assert_ratio,
    assert_total_count,
    build_canonical_environment,
    build_draft_certificate,
    build_environment_with_issued_certificate,
    complete_claim_documents,
    create_declaration,
    create_open_policy,
    create_vessel,
    declare_ga_event,
    ga_posting_for_certificate,
    issue_certificate,
    issue_ga_security_calls,
    make_assured_headers,
    open_claim_file,
    read_certificate,
    read_claim_file,
    read_declaration,
    read_ga_event,
    read_ga_posting,
    read_policy,
    read_port,
    read_vessel,
    set_clock,
    submit_declaration,
)

# --- the COLLECT book: the same shipment, with freight left out of the base ---
COLLECT_INSURED_VALUE = 1105500.00
COLLECT_BASE_PREMIUM = 5223.49
COLLECT_WAR_PREMIUM = 663.30
COLLECT_STRIKES_PREMIUM = 281.90
COLLECT_TOTAL_PREMIUM = 6168.69
EFFECTIVE_MARINE_RATE = 4.7250

# --- the AMBER discharge port: 0.600 per mille lifted by the 1.5 multiplier ---
AMBER_MULTIPLIER = 1.5
GREEN_MULTIPLIER = 1.0
AMBER_WAR_PREMIUM = 1039.50
AMBER_TOTAL_PREMIUM = 6791.41
NO_WAR_TOTAL_PREMIUM = 5457.38
TWO_CERTIFICATE_PREMIUM_BOOKED = 12248.79
TWO_CERTIFICATE_VALUE_BOOKED = 2310000.00

# --- the age screen ---
OVERAGE_SURCHARGE = 0.25
NO_SURCHARGE = 0.00

# --- transit termination: one discharge date, four different answers ---
DISCHARGE_DATE = "2026-09-05T00:00:00Z"
TERMINATION_30_DAY_PORT = "2026-10-05T00:00:00Z"
TERMINATION_60_DAY_CEILING = "2026-11-04T00:00:00Z"
TERMINATION_OVERSIDE = "2026-09-05T00:00:00Z"
TERMINATION_POLICY_EXPIRY = "2026-09-20T00:00:00Z"
SHORT_POLICY_EXPIRY = "2026-09-20T00:00:00Z"
SMALL_DECLARED_VALUE = 400000

# --- general average over a single contributor ---
GA_ADJUSTER_FEE = 7500.00
GA_TOTAL_ALLOWANCE = 157500.00
GA_SOLE_CONTRIBUTORY_VALUE = 1155000.00
GA_SOLE_RATE = 0.136364
GA_SOLE_CONTRIBUTION = 157500.00
GA_SOLE_EXPECTED_DEPOSIT = 31500.00

# --- the reporting period sweep ---
PERIOD_START = "2026-06-01T00:00:00Z"
PERIOD_END = "2026-07-01T00:00:00Z"
CLOCK_INSIDE_PERIOD = "2026-06-15T00:00:00Z"
CLOCK_AFTER_PERIOD = "2026-07-10T00:00:00Z"
SMALL_TOTAL_PREMIUM = 2232.00

# --- the empty period ---
EMPTY_PERIOD_A = ("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")
EMPTY_PERIOD_B = ("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z")
ZERO_BASE_DECLARED = 100.00
ZERO_BASE_VARIANCE_PCT = 100.00

# --- a loss below the pinned excess ---
SMALL_DAMAGE_PCT = 0.10
SMALL_GROSS_LOSS = 1155.00
PINNED_DEDUCTIBLE = 2500.00
TIME_BAR_INSTANT = "2027-09-05T00:00:00Z"


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------
def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so two spellings of one moment compare equal."""
    assert value is not None, "expected an ISO 8601 instant, got None"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant(actual: str, expected: str, label: str = "instant") -> None:
    """Assert a timestamp field names exactly the expected instant."""
    assert _instant(actual) == _instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def _collect_basis_environment(api: ApiClient) -> JsonDict:
    """
    The canonical book of business on a `COLLECT` open cover: two green ports,
    an S3 class loading 0.35, a 2015-built hull screened to `APPROVED`, and a
    cover quoting 3.500 / 0.600 / 0.255 with a 0.10 markup.
    """
    return build_canonical_environment(
        api,
        policy_overrides={"policy_number": "OP-2596-COLLECT",
                          "freight_basis": "COLLECT"},
    )


def _amber_discharge_environment(api: ApiClient) -> JsonDict:
    """
    The canonical book of business with the discharge port registered directly
    at tier `AMBER`, so the voyage's two multipliers are 1.0 and 1.5.
    """
    return build_canonical_environment(
        api,
        loading_port=dict(PORT_SGSIN, war_risk_tier="GREEN"),
        discharge_port=dict(PORT_NLRTM, war_risk_tier="AMBER"),
    )


def _screen_hull(api: ApiClient, name: str, imo_number: str, year_built: int,
                 classification_society: str) -> JsonDict:
    """
    Register one conveyance and run its classification and age screen. Asserts
    the screen answers 200 and that the review is the hull's second write.
    """
    hull = create_vessel(api, review=False, name=name, imo_number=imo_number,
                         year_built=year_built,
                         classification_society=classification_society)
    assert_common_fields(hull, expected_version=1, label="vessel at registration")
    screened = validate_success(
        api.review_vessel_classification(hull["id"], UNDERWRITER))
    assert_common_fields(screened, expected_version=2, label="screened vessel")
    return screened


def _issue_small_declared_shipment(api: ApiClient, env: JsonDict,
                                   certificate_number: str,
                                   sailing_date: str) -> JsonDict:
    """
    Declare and issue a 400000.00 declared-value shipment that buys neither war
    nor strikes cover, discharging 2026-09-05.
    """
    draft = build_draft_certificate(
        api, env,
        base=CERTIFICATE_DECLARED_SHIPMENT,
        certificate_number=certificate_number,
        declared_value=SMALL_DECLARED_VALUE,
        sailing_date=sailing_date,
        discharge_date=DISCHARGE_DATE,
        package_count=40,
        gross_weight_kg=6000,
        war_cover_requested=False,
        strikes_cover_requested=False,
    )
    return issue_certificate(api, draft["id"], env["policy_id"])


def _ga_called_over_one_contributor(api: ApiClient) -> JsonDict:
    """
    One issued CIF certificate of 1155000.00 on MV Kite sailing 2026-08-10, and
    a general average declared on that conveyance with a sacrifice of 120000.00
    and a salvage award of 30000.00, taken through its security call.
    """
    env = build_environment_with_issued_certificate(api)
    event = declare_ga_event(api, env["vessel_id"])
    env["ga_event"] = issue_ga_security_calls(api, event["id"])
    env["ga_event_id"] = event["id"]
    env["posting"] = ga_posting_for_certificate(
        api, event["id"], env["certificate_id"])
    return env


def _claim_below_the_excess(api: ApiClient) -> JsonDict:
    """
    An issued CIF certificate of 1155000.00 with a 2500.00 excess pinned on it,
    and a fully documented claim measuring 0.10 percent damage on a claimed
    1155.00 — under the class's 500000.00 survey trigger.
    """
    env = build_environment_with_issued_certificate(api)
    env["claim"] = open_claim_file(api, env["certificate_id"],
                                   claimed_amount=SMALL_GROSS_LOSS,
                                   damage_percentage=SMALL_DAMAGE_PCT)
    env["claim_id"] = env["claim"]["id"]
    complete_claim_documents(api, env["claim_id"])
    return env


# ---------------------------------------------------------------------------
# The freight switch on the insured-value base
# ---------------------------------------------------------------------------
def test_collect_freight_is_left_out_of_the_insured_value_base(api: ApiClient) -> None:
    """
    A COLLECT cover insures invoice plus duty only, even when freight is quoted.

    The declared ocean freight joins that base only when the parent policy's `freight_basis` is `PREPAID`; under `COLLECT` the assured has not yet paid the freight, so it is excluded from the base.

    Design: Corner/calculations/collect_freight_is_excluded_from_the_insured_value_base
    """
    env = _collect_basis_environment(api)
    draft = build_draft_certificate(api, env, base=CERTIFICATE_CIF_SHIPMENT,
                                    certificate_number="CERT-COLLECT")
    issued = issue_certificate(api, draft["id"], env["policy_id"])

    # (1000000.00 + 5000.00) * 1.10 — the quoted 45000.00 freight never enters.
    assert_money(issued["insured_value"], COLLECT_INSURED_VALUE,
                 "certificate.insured_value")

    hull = read_vessel(api, env["vessel_id"])
    discharge_port = read_port(api, env["discharge_port_id"])
    assert_money(hull["accumulated_insured_value"], COLLECT_INSURED_VALUE,
                 "vessel.accumulated_insured_value")
    assert_money(discharge_port["accumulated_insured_value"],
                 COLLECT_INSURED_VALUE, "port.accumulated_insured_value")


def test_collect_premium_components_follow_the_reduced_base(api: ApiClient) -> None:
    """
    Every premium component falls with the COLLECT base and the total is the sum
    of the three already-rounded components.

    `total_premium_amount` is then the sum of those three already-rounded components — never a re-derivation from the unrounded figures, and never recomputed after issue.

    Design: Corner/calculations/collect_freight_is_excluded_from_the_insured_value_base
    """
    env = _collect_basis_environment(api)
    draft = build_draft_certificate(api, env, base=CERTIFICATE_CIF_SHIPMENT,
                                    certificate_number="CERT-COLLECT")
    issued = issue_certificate(api, draft["id"], env["policy_id"])

    # 3.500 loaded by 0.35, no hull surcharge: the rate is unmoved by freight.
    assert_rate(issued["effective_rate_per_mille"], EFFECTIVE_MARINE_RATE,
                label="certificate.effective_rate_per_mille")
    # 1105500 / 1000 * 4.7250 = 5223.4875, and 1105.5 * 0.255 = 281.9025.
    assert_amounts(issued, {
        "base_premium_amount": COLLECT_BASE_PREMIUM,
        "war_premium_amount": COLLECT_WAR_PREMIUM,
        "strikes_premium_amount": COLLECT_STRIKES_PREMIUM,
        "total_premium_amount": COLLECT_TOTAL_PREMIUM,
    }, "certificate")


# ---------------------------------------------------------------------------
# The war rate takes the worse of the two ports
# ---------------------------------------------------------------------------
def test_war_rate_takes_the_worse_of_the_two_port_tiers(api: ApiClient) -> None:
    """
    A green loading port cannot dilute an amber discharge port.

    The two ports of the voyage are compared and the **worse** of them governs: the port multiplier is the higher of the loading port's `war_rate_multiplier` and the discharge port's.

    Design: Corner/calculations/war_rate_takes_the_worse_port_tier_and_zero_when_cover_is_declined
    """
    env = _amber_discharge_environment(api)
    assert_rate(read_port(api, env["loading_port_id"])["war_rate_multiplier"],
                GREEN_MULTIPLIER, places=2, label="loading port multiplier")
    assert_rate(read_port(api, env["discharge_port_id"])["war_rate_multiplier"],
                AMBER_MULTIPLIER, places=2, label="discharge port multiplier")

    draft = build_draft_certificate(api, env, base=CERTIFICATE_CIF_SHIPMENT,
                                    certificate_number="CERT-WAR")
    issued = issue_certificate(api, draft["id"], env["policy_id"])

    # round(0.600 * 1.5, 4) = 0.9000, and 1155000 / 1000 * 0.9000 = 1039.50.
    assert_amounts(issued, {
        "base_premium_amount": 5457.38,
        "war_premium_amount": AMBER_WAR_PREMIUM,
        "strikes_premium_amount": 294.53,
        "total_premium_amount": AMBER_TOTAL_PREMIUM,
    }, "certificate")
    assert issued["war_cover_status"] == "ATTACHED", (
        f"war axis: expected ATTACHED, got {issued['war_cover_status']}"
    )


def test_declining_war_and_strikes_zeroes_both_components(api: ApiClient) -> None:
    """
    A shipment that buys neither cover pays only its marine premium, and its war
    axis reaches the terminal state for that axis.

    `war_premium_amount` is the insured value divided by 1000 multiplied by the effective war rate and rounded the same way when war cover is requested, and exactly 0.00 when it is not requested or not obtainable.

    Design: Corner/calculations/war_rate_takes_the_worse_port_tier_and_zero_when_cover_is_declined
    """
    env = _amber_discharge_environment(api)
    covered_draft = build_draft_certificate(
        api, env, base=CERTIFICATE_CIF_SHIPMENT, certificate_number="CERT-WAR")
    bare_draft = build_draft_certificate(
        api, env, base=CERTIFICATE_CIF_SHIPMENT, certificate_number="CERT-NOWAR",
        war_cover_requested=False, strikes_cover_requested=False)

    covered = issue_certificate(api, covered_draft["id"], env["policy_id"])
    bare = issue_certificate(api, bare_draft["id"], env["policy_id"])

    assert bare["war_cover_status"] == "NOT_TAKEN", (
        f"war axis: expected NOT_TAKEN, got {bare['war_cover_status']}"
    )
    # The amber multiplier is never applied to the strikes rate either.
    assert_amounts(bare, {
        "war_premium_amount": 0.00,
        "strikes_premium_amount": 0.00,
        "base_premium_amount": NO_WAR_TOTAL_PREMIUM,
        "total_premium_amount": NO_WAR_TOTAL_PREMIUM,
    }, "declined certificate")
    assert_money(covered["total_premium_amount"], AMBER_TOTAL_PREMIUM,
                 "covered certificate.total_premium_amount")

    policy = read_policy(api, env["policy_id"])
    assert_amounts(policy, {
        "aggregate_premium_booked": TWO_CERTIFICATE_PREMIUM_BOOKED,
        "aggregate_insured_value_booked": TWO_CERTIFICATE_VALUE_BOOKED,
    }, "open policy")


# ---------------------------------------------------------------------------
# The classification and age screen at its four breakpoints
# ---------------------------------------------------------------------------
def test_hull_aged_exactly_twenty_five_years_is_approved(api: ApiClient) -> None:
    """
    A 2001 build against a 2026 clock is exactly 25 and carries no surcharge.

    Both age thresholds are strictly greater than: with a build year of 2001 and the clock in 2026 the age is exactly 25 and the vessel is `APPROVED`; 2000 gives 26 and `OVERAGE_SURCHARGED`; 1996 gives 30 and is still `OVERAGE_SURCHARGED`; 1995 gives 31 and is `BLOCKED`.

    Design: Corner/calculations/vessel_age_thresholds_at_25_26_30_and_31_years
    """
    set_clock(api, DEFAULT_CLOCK)
    screened = _screen_hull(api, "MV Age25", "9100011", 2001, "LR")

    assert screened["status"] == "APPROVED", (
        f"vessel.status: expected APPROVED, got {screened['status']}"
    )
    assert_rate(screened["overage_surcharge_pct"], NO_SURCHARGE, places=2,
                label="vessel.overage_surcharge_pct")


def test_hull_aged_twenty_six_years_is_surcharged(api: ApiClient) -> None:
    """
    A 2000 build against a 2026 clock is 26 and attracts the overage loading.

    Otherwise, if the age is greater than 25 years the vessel goes to `OVERAGE_SURCHARGED` and `overage_surcharge_pct` is set to 0.25, so every certificate subsequently issued on that hull carries a twenty-five percent loading on its effective marine rate.

    Design: Corner/calculations/vessel_age_thresholds_at_25_26_30_and_31_years
    """
    set_clock(api, DEFAULT_CLOCK)
    screened = _screen_hull(api, "MV Age26", "9100012", 2000, "LR")

    assert screened["status"] == "OVERAGE_SURCHARGED", (
        f"vessel.status: expected OVERAGE_SURCHARGED, got {screened['status']}"
    )
    assert_rate(screened["overage_surcharge_pct"], OVERAGE_SURCHARGE, places=2,
                label="vessel.overage_surcharge_pct")


def test_hull_aged_exactly_thirty_years_is_still_only_surcharged(api: ApiClient) -> None:
    """
    A 1996 build against a 2026 clock is exactly 30 and is not yet uninsurable.

    Both age thresholds are strictly greater than: with a build year of 2001 and the clock in 2026 the age is exactly 25 and the vessel is `APPROVED`; 2000 gives 26 and `OVERAGE_SURCHARGED`; 1996 gives 30 and is still `OVERAGE_SURCHARGED`; 1995 gives 31 and is `BLOCKED`.

    Design: Corner/calculations/vessel_age_thresholds_at_25_26_30_and_31_years
    """
    set_clock(api, DEFAULT_CLOCK)
    screened = _screen_hull(api, "MV Age30", "9100013", 1996, "ABS")

    assert screened["status"] == "OVERAGE_SURCHARGED", (
        f"vessel.status: expected OVERAGE_SURCHARGED, got {screened['status']}"
    )
    assert_rate(screened["overage_surcharge_pct"], OVERAGE_SURCHARGE, places=2,
                label="vessel.overage_surcharge_pct")


def test_hull_aged_thirty_one_years_is_blocked_with_no_surcharge(api: ApiClient) -> None:
    """
    A 1995 build against a 2026 clock is 31, and a blocked hull carries no loading.

    Otherwise, if the age is greater than 30 years the vessel goes to `BLOCKED` with `overage_surcharge_pct` 0.

    Design: Corner/calculations/vessel_age_thresholds_at_25_26_30_and_31_years
    """
    set_clock(api, DEFAULT_CLOCK)
    screened = _screen_hull(api, "MV Age31", "9100014", 1995, "DNV")

    assert screened["status"] == "BLOCKED", (
        f"vessel.status: expected BLOCKED, got {screened['status']}"
    )
    assert_rate(screened["overage_surcharge_pct"], NO_SURCHARGE, places=2,
                label="vessel.overage_surcharge_pct")


def test_unclassed_hull_is_blocked_whatever_its_age(api: ApiClient) -> None:
    """
    A two-year-old hull on no class is blocked and carries no loading.

    If the society is `UNCLASSED` the vessel goes to `BLOCKED` with `overage_surcharge_pct` set to 0, at any age — a two-year-old ship on no class is still uninsurable.

    Design: Corner/calculations/vessel_age_thresholds_at_25_26_30_and_31_years
    """
    set_clock(api, DEFAULT_CLOCK)
    screened = _screen_hull(api, "MV NewUnclassed", "9100015", 2024, "UNCLASSED")

    assert screened["status"] == "BLOCKED", (
        f"vessel.status: expected BLOCKED, got {screened['status']}"
    )
    assert_rate(screened["overage_surcharge_pct"], NO_SURCHARGE, places=2,
                label="vessel.overage_surcharge_pct")


# ---------------------------------------------------------------------------
# The end of transit: three competing clocks, one discharge date
# ---------------------------------------------------------------------------
def test_port_free_storage_days_bind_the_end_of_transit(api: ApiClient) -> None:
    """
    A 30-day discharge port closes the window before the sixty-day ceiling does.

    When it is true, the termination instant is the earliest of three candidates: the discharge instant plus the discharge port's `storage_free_days` days, the discharge instant plus the sixty-day warehouse-to-warehouse ceiling, and the policy's `expiry_at`.

    Design: Corner/calculations/transit_termination_binds_on_the_earliest_of_three_clocks
    """
    env = build_canonical_environment(api)
    issued = _issue_small_declared_shipment(api, env, "CERT-STD30",
                                            "2026-08-10T00:00:00Z")

    assert issued["status"] == "ISSUED", (
        f"certificate.status: expected ISSUED, got {issued['status']}"
    )
    _assert_instant(issued["attachment_at"], "2026-08-10T00:00:00Z",
                    "certificate.attachment_at")
    _assert_instant(issued["transit_termination_at"], TERMINATION_30_DAY_PORT,
                    "certificate.transit_termination_at")


def test_sixty_day_ceiling_binds_when_the_port_is_as_generous(api: ApiClient) -> None:
    """
    A port allowing 60 free storage days meets the warehouse-to-warehouse ceiling.

    When it is true, the termination instant is the earliest of three candidates: the discharge instant plus the discharge port's `storage_free_days` days, the discharge instant plus the sixty-day warehouse-to-warehouse ceiling, and the policy's `expiry_at`.

    Design: Corner/calculations/transit_termination_binds_on_the_earliest_of_three_clocks
    """
    env = build_canonical_environment(
        api,
        discharge_port=dict(PORT_NLRTM, unlocode="MYPKG", name="Port Klang",
                            country_code="MY", storage_free_days=60),
    )
    issued = _issue_small_declared_shipment(api, env, "CERT-CAP60",
                                            "2026-08-11T00:00:00Z")

    assert issued["status"] == "ISSUED", (
        f"certificate.status: expected ISSUED, got {issued['status']}"
    )
    _assert_instant(issued["attachment_at"], "2026-08-11T00:00:00Z",
                    "certificate.attachment_at")
    # 2026-09-05 plus sixty whole days, on a UTC midnight boundary.
    _assert_instant(issued["transit_termination_at"], TERMINATION_60_DAY_CEILING,
                    "certificate.transit_termination_at")


def test_cover_ending_overside_ignores_the_storage_window(api: ApiClient) -> None:
    """
    A cover that is not warehouse-to-warehouse terminates on the discharge instant.

    When the policy's `warehouse_to_warehouse` is false, cover ends on discharge overside and the termination instant is simply the discharge date at `00:00:00Z`.

    Design: Corner/calculations/transit_termination_binds_on_the_earliest_of_three_clocks
    """
    env = build_canonical_environment(
        api,
        policy_overrides={"policy_number": "OP-WW-OFF",
                          "warehouse_to_warehouse": False},
    )
    issued = _issue_small_declared_shipment(api, env, "CERT-WWOFF",
                                            "2026-08-12T00:00:00Z")

    assert issued["status"] == "ISSUED", (
        f"certificate.status: expected ISSUED, got {issued['status']}"
    )
    _assert_instant(issued["attachment_at"], "2026-08-12T00:00:00Z",
                    "certificate.attachment_at")
    # The discharge port's 30 free storage days are never consulted.
    _assert_instant(issued["transit_termination_at"], TERMINATION_OVERSIDE,
                    "certificate.transit_termination_at")


def test_policy_expiry_truncates_the_storage_window(api: ApiClient) -> None:
    """
    A cover expiring inside the storage window cuts transit short at expiry.

    When it is true, the termination instant is the earliest of three candidates: the discharge instant plus the discharge port's `storage_free_days` days, the discharge instant plus the sixty-day warehouse-to-warehouse ceiling, and the policy's `expiry_at`.

    Design: Corner/calculations/transit_termination_binds_on_the_earliest_of_three_clocks
    """
    env = build_canonical_environment(
        api,
        policy_overrides={"policy_number": "OP-SHORT",
                          "expiry_at": SHORT_POLICY_EXPIRY},
    )
    issued = _issue_small_declared_shipment(api, env, "CERT-SHORT",
                                            "2026-08-13T00:00:00Z")

    assert issued["status"] == "ISSUED", (
        f"certificate.status: expected ISSUED, got {issued['status']}"
    )
    _assert_instant(issued["attachment_at"], "2026-08-13T00:00:00Z",
                    "certificate.attachment_at")
    # Twenty-five free storage days remain unused at the discharge port.
    _assert_instant(issued["transit_termination_at"], TERMINATION_POLICY_EXPIRY,
                    "certificate.transit_termination_at")


# ---------------------------------------------------------------------------
# General average: one contributor absorbs the whole residual
# ---------------------------------------------------------------------------
def test_sole_contributor_absorbs_the_whole_rounding_residual(api: ApiClient) -> None:
    """
    The rate is rounded to six decimals, so the only bucket takes the residual
    and the contribution balances the allowance to the cent.

    The contributors are ordered by contributory value descending, ties broken by `created_at` ascending, and the whole residual — the total allowance minus the sum of the raw contributions, which may be positive or negative — is applied to the **first** bucket of that ordering.

    Design: Corner/calculations/general_average_single_contributor_absorbs_the_whole_rounding_residual
    """
    env = _ga_called_over_one_contributor(api)

    event = read_ga_event(api, env["ga_event_id"], CLAIMS_ADJUSTER)
    assert_money(event["total_contributory_value"], GA_SOLE_CONTRIBUTORY_VALUE,
                 "ga event.total_contributory_value")
    # round(157500 / 1155000, 6) = 0.136364.
    assert_ratio(event["contribution_rate"], GA_SOLE_RATE,
                 "ga event.contribution_rate")

    assert_total_count(
        api.list_ga_security_postings(CLAIMS_ADJUSTER,
                                      {"ga_event_id": env["ga_event_id"]}),
        1, "security postings of the event")

    posting = read_ga_posting(api, env["posting"]["id"], CLAIMS_ADJUSTER)
    assert_money(posting["contributory_value"], GA_SOLE_CONTRIBUTORY_VALUE,
                 "posting.contributory_value")
    # The raw 157500.42 plus the residual of -0.42.
    assert_money(posting["contribution_amount"], GA_SOLE_CONTRIBUTION,
                 "posting.contribution_amount")
    assert posting["status"] == "REQUIRED", (
        f"posting.status: expected REQUIRED, got {posting['status']}"
    )

    certificate = read_certificate(api, env["certificate_id"])
    assert_money(certificate["ga_contribution_amount"], GA_SOLE_CONTRIBUTION,
                 "certificate.ga_contribution_amount")


def test_adjuster_fee_is_five_percent_of_the_pre_fee_allowance(api: ApiClient) -> None:
    """
    The fee is charged on sacrifice plus salvage award only, never on itself.

    First the average adjuster's fee: it is five percent of the **pre-fee** allowance only — the sum of `sacrifice_amount` and `salvage_award_amount` — rounded half up to 2 decimals, so the fee is never charged on itself.

    Design: Corner/calculations/general_average_single_contributor_absorbs_the_whole_rounding_residual
    """
    env = _ga_called_over_one_contributor(api)

    event = read_ga_event(api, env["ga_event_id"], CLAIMS_ADJUSTER)
    # Five percent of 150000.00, and the allowance is 150000.00 plus that fee.
    assert_amounts(event, {
        "adjuster_fee_amount": GA_ADJUSTER_FEE,
        "total_allowance_amount": GA_TOTAL_ALLOWANCE,
    }, "ga event")
    assert event["status"] == "SECURITY_COLLECTING", (
        f"ga event.status: expected SECURITY_COLLECTING, got {event['status']}"
    )
    assert event["postings_required_count"] == 1, (
        f"ga event.postings_required_count: expected 1, "
        f"got {event['postings_required_count']}"
    )
    assert event["postings_posted_count"] == 0, (
        f"ga event.postings_posted_count: expected 0, "
        f"got {event['postings_posted_count']}"
    )


def test_cash_deposit_is_twenty_percent_of_the_final_contribution(api: ApiClient) -> None:
    """
    The expected deposit is taken on the allocated contribution, not the raw one.

    Whether cash is wanted as well as a guarantee is then decided per posting: `cash_deposit_required` is true when the contribution amount exceeds 25000, and where it is true, `cash_deposit_expected_amount` is twenty percent of the contribution amount rounded half up to 2 decimals, while a posting that needs no cash carries an expected deposit of 0.00.

    Design: Corner/calculations/general_average_single_contributor_absorbs_the_whole_rounding_residual
    """
    env = _ga_called_over_one_contributor(api)

    posting = read_ga_posting(api, env["posting"]["id"], CLAIMS_ADJUSTER)
    assert posting["cash_deposit_required"] is True, (
        f"posting.cash_deposit_required: expected True, "
        f"got {posting['cash_deposit_required']}"
    )
    # Twenty percent of the final 157500.00, not of the raw 157500.42.
    assert_money(posting["cash_deposit_expected_amount"],
                 GA_SOLE_EXPECTED_DEPOSIT, "posting.cash_deposit_expected_amount")


# ---------------------------------------------------------------------------
# The reporting period sweep
# ---------------------------------------------------------------------------
def test_declaration_sweep_takes_only_certificates_issued_inside_the_period(
        api: ApiClient) -> None:
    """
    Of three certificates, only the one issued inside the half-open window is
    stamped, counted and reconciled.

    The sweep then claims certificates: every certificate of the policy whose `issued_at` falls inside the half-open window from `period_start` up to but excluding `period_end`, and whose `premium_declaration_id` is still null, is stamped with this declaration's identifier.

    Design: Corner/calculations/declaration_sweep_takes_only_issued_certificates_inside_the_period
    """
    set_clock(api, PERIOD_START)
    env = build_canonical_environment(api)
    drafts = {
        number: build_draft_certificate(
            api, env,
            base=CERTIFICATE_DECLARED_SHIPMENT,
            certificate_number=number,
            declared_value=SMALL_DECLARED_VALUE,
            package_count=40,
            gross_weight_kg=6000,
        )
        for number in ("CERT-IN", "CERT-OUT", "CERT-DRAFT")
    }

    set_clock(api, CLOCK_INSIDE_PERIOD)
    issue_certificate(api, drafts["CERT-IN"]["id"], env["policy_id"])
    set_clock(api, CLOCK_AFTER_PERIOD)
    issue_certificate(api, drafts["CERT-OUT"]["id"], env["policy_id"])

    declaration = create_declaration(api, env["policy_id"], PERIOD_START, PERIOD_END)
    submitted = submit_declaration(api, declaration["id"], env["policy_id"],
                                   SMALL_TOTAL_PREMIUM)

    # One certificate of 1890.00 + 240.00 + 102.00 belongs to the period.
    assert_money(submitted["computed_premium_total"], SMALL_TOTAL_PREMIUM,
                 "declaration.computed_premium_total")
    assert submitted["certificate_count"] == 1, (
        f"declaration.certificate_count: expected 1, "
        f"got {submitted['certificate_count']}"
    )
    assert_money(submitted["variance_amount"], 0.00, "declaration.variance_amount")
    assert_money(submitted["variance_pct"], 0.00, "declaration.variance_pct")
    assert submitted["status"] == "SUBMITTED", (
        f"declaration.status: expected SUBMITTED, got {submitted['status']}"
    )
    assert submitted["submission_count"] == 1, (
        f"declaration.submission_count: expected 1, "
        f"got {submitted['submission_count']}"
    )
    assert submitted["submitted_by_user_id"] == env["policy_id"], (
        "declaration.submitted_by_user_id must record the acting assured"
    )

    inside = read_certificate(api, drafts["CERT-IN"]["id"])
    outside = read_certificate(api, drafts["CERT-OUT"]["id"])
    never_issued = read_certificate(api, drafts["CERT-DRAFT"]["id"])
    assert inside["premium_declaration_id"] == declaration["id"], (
        "the certificate issued inside the window must be stamped"
    )
    assert outside["premium_declaration_id"] is None, (
        "the certificate issued after period_end must stay unstamped"
    )
    assert never_issued["premium_declaration_id"] is None, (
        "a certificate that never left DRAFT is not reportable"
    )
    assert never_issued["status"] == "DRAFT", (
        f"certificate.status: expected DRAFT, got {never_issued['status']}"
    )

    assert_total_count(
        api.list_certificates(UNDERWRITER,
                              {"premium_declaration_id": declaration["id"]}),
        1, "certificates of the declaration")


# ---------------------------------------------------------------------------
# A reporting period with nothing in it
# ---------------------------------------------------------------------------
def test_declaration_against_an_empty_period_uses_the_pinned_zero_base_rule(
        api: ApiClient) -> None:
    """
    Declaring 100.00 against a computed zero is a full hundred percent variance,
    while declaring nothing against nothing is a perfect match.

    When the computed total is exactly zero the ratio is undefined, and the rule is pinned rather than left to the implementer: a declaration that reports zero against a computed zero has a variance percentage of 0.00, while any non-zero declaration against a computed zero has a variance percentage of exactly 100.00.

    Design: Corner/calculations/zero_computed_base_declaration_reports_a_full_hundred_percent_variance
    """
    policy = create_open_policy(api, policy_number="OP-2596-EMPTY")
    assured = make_assured_headers(policy["id"])

    first = validate_success(api.create_premium_declaration(
        {"open_policy_id": policy["id"], "period_start": EMPTY_PERIOD_A[0],
         "period_end": EMPTY_PERIOD_A[1]}, assured), 201)
    # A period beginning exactly at another's period_end does not overlap.
    second = validate_success(api.create_premium_declaration(
        {"open_policy_id": policy["id"], "period_start": EMPTY_PERIOD_B[0],
         "period_end": EMPTY_PERIOD_B[1]}, assured), 201)

    reported = submit_declaration(api, first["id"], policy["id"],
                                  ZERO_BASE_DECLARED)
    assert_amounts(reported, {
        "computed_premium_total": 0.00,
        "variance_amount": ZERO_BASE_DECLARED,
        "variance_pct": ZERO_BASE_VARIANCE_PCT,
    }, "declaration reporting 100.00")
    assert reported["certificate_count"] == 0, (
        f"declaration.certificate_count: expected 0, "
        f"got {reported['certificate_count']}"
    )

    matched = submit_declaration(api, second["id"], policy["id"], 0.00)
    assert_amounts(matched, {
        "variance_amount": 0.00,
        "variance_pct": 0.00,
    }, "declaration reporting 0.00")

    stored = read_declaration(api, first["id"], assured)
    assert_money(stored["variance_pct"], ZERO_BASE_VARIANCE_PCT,
                 "declaration.variance_pct")


def test_hundred_percent_variance_adjusts_the_declaration_and_suspends_the_cover(
        api: ApiClient) -> None:
    """
    A variance above the tolerance books the adjustment on the declaration only,
    and a variance above four times it suspends the cover.

    When the variance percentage is strictly above 2.5 percent, the declaration goes `UNDER_AUDIT → ADJUSTED` and `audit_adjustment_amount` is set to the absolute value of `variance_amount` — the adjustment is booked on the declaration only, and the policy's `aggregate_premium_booked` is deliberately *not* touched by it.

    Design: Corner/calculations/zero_computed_base_declaration_reports_a_full_hundred_percent_variance
    """
    policy = create_open_policy(api, policy_number="OP-2596-EMPTY")
    assured = make_assured_headers(policy["id"])
    declaration = get_success_data(api.create_premium_declaration(
        {"open_policy_id": policy["id"], "period_start": EMPTY_PERIOD_A[0],
         "period_end": EMPTY_PERIOD_A[1]}, assured))
    submit_declaration(api, declaration["id"], policy["id"], ZERO_BASE_DECLARED)

    validate_success(api.start_declaration_audit(declaration["id"], PREMIUM_AUDITOR))
    audited = validate_success(api.finish_declaration_audit(
        declaration["id"], PREMIUM_AUDITOR,
        {"audit_note": "no certificates issued in the period"}))

    assert audited["status"] == "ADJUSTED", (
        f"declaration.status: expected ADJUSTED, got {audited['status']}"
    )
    assert_money(audited["audit_adjustment_amount"], ZERO_BASE_DECLARED,
                 "declaration.audit_adjustment_amount")

    suspended = read_policy(api, policy["id"])
    assert suspended["status"] == "SUSPENDED", (
        f"policy.status: expected SUSPENDED, got {suspended['status']}"
    )
    assert_money(suspended["aggregate_premium_booked"], 0.00,
                 "policy.aggregate_premium_booked")


# ---------------------------------------------------------------------------
# A loss smaller than the pinned excess
# ---------------------------------------------------------------------------
def test_loss_below_the_deductible_floors_the_indemnity_at_zero(api: ApiClient) -> None:
    """
    A 1155.00 gross loss against a 2500.00 excess indemnifies nothing, and the
    excess is only absorbed up to the loss.

    `adjusted_amount` is then the gross loss minus the deductible, floored at 0.00 so it can never go negative, and `deductible_applied_amount` is the lesser of the deductible and the gross loss — a deductible larger than the loss is only absorbed up to the loss.

    Design: Corner/calculations/claim_below_the_deductible_floors_at_zero_and_settles_at_zero
    """
    env = _claim_below_the_excess(api)
    assert_money(read_certificate(api, env["certificate_id"])["deductible_amount"],
                 PINNED_DEDUCTIBLE, "certificate.deductible_amount")

    adjusted = adjust_claim_file(api, env["claim_id"])

    assert adjusted["status"] == "ADJUSTED", (
        f"claim.status: expected ADJUSTED, got {adjusted['status']}"
    )
    # 1155000.00 * 0.10 / 100 = 1155.00, and 1155.00 - 2500.00 clamps at 0.00.
    assert_amounts(adjusted, {
        "adjusted_amount": 0.00,
        "deductible_applied_amount": SMALL_GROSS_LOSS,
    }, "claim")
    assert adjusted["adjusted_by_user_id"] == ADJUSTER_USER_ID, (
        "claim.adjusted_by_user_id must record the acting adjuster"
    )
    stored = read_claim_file(api, env["claim_id"], CLAIMS_ADJUSTER)
    _assert_instant(stored["time_bar_at"], TIME_BAR_INSTANT, "claim.time_bar_at")


def test_zero_indemnity_claim_still_settles_at_zero(api: ApiClient) -> None:
    """
    Settlement is not gated on a positive indemnity: a nil adjustment settles nil.

    On success the claim reaches the terminal `SETTLED`, `settled_amount` is set to `adjusted_amount`, `net_loss_amount` is set to the adjusted amount minus whatever has been recovered so far, and `settled_by_user_id` records the settling adjuster.

    Design: Corner/calculations/claim_below_the_deductible_floors_at_zero_and_settles_at_zero
    """
    env = _claim_below_the_excess(api)
    adjust_claim_file(api, env["claim_id"])

    settled = get_success_data(
        api.settle_claim_file(env["claim_id"], CLAIMS_ADJUSTER_2))

    assert settled["status"] == "SETTLED", (
        f"claim.status: expected SETTLED, got {settled['status']}"
    )
    assert_amounts(settled, {
        "settled_amount": 0.00,
        "net_loss_amount": 0.00,
    }, "claim")

    # A nil settlement does not rewrite the certificate's exposure.
    certificate = read_certificate(api, env["certificate_id"])
    assert certificate["status"] == "CLAIMED", (
        f"certificate.status: expected CLAIMED, got {certificate['status']}"
    )
