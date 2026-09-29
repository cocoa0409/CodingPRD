"""
Lifecycle transitions of the open cover, the certificate and the recovery axis.

Exercises the state movements each trigger is allowed to make and the refusals
it must produce when the row is in the wrong state: activating an open cover,
declaring and issuing a shipment, cancelling and endorsing an issued
certificate, screening a hull before it may carry risk, reinstating war cover
after a port listing, and serving subrogation notice on the time bar.
"""

from typing import List, Optional

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    CERTIFICATE_DECLARED_SHIPMENT,
    CLAIMS_ADJUSTER_2,
    COMPLIANCE_OFFICER,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
    ERR_SUBROGATION_TIME_BARRED,
    ERR_VESSEL_BLOCKED,
    EXPECTED_CLAIM_ADJUSTED_DEPRECIATION,
    EXPECTED_CLAIM_DEDUCTIBLE_APPLIED,
    EXPECTED_INSURED_VALUE_CIF,
    EXPECTED_STRIKES_PREMIUM,
    EXPECTED_TOTAL_PREMIUM,
    EXPECTED_WAR_PREMIUM,
    EXPECTED_WAR_STRIKES_RETURN,
    PORT_USNYC,
    UNDERWRITER,
    VESSEL_COMET,
    VESSEL_OLD_SALT,
    ApiClient,
    JsonDict,
    assert_money,
    assert_rate,
    assert_total_count,
    build_adjusted_claim,
    build_canonical_environment,
    build_cancelled_certificate,
    build_draft_certificate,
    build_environment_with_issued_certificate,
    build_issued_certificate,
    create_open_policy,
    create_port,
    create_vessel,
    find_row,
    make_assured_headers,
    policy_version,
    read_certificate,
    read_claim_file,
    read_policy,
    read_vessel,
    set_clock,
)

# --- the open cover's own excess, pinned onto every certificate it writes ----
POLICY_DEDUCTIBLE = 2500.00

# --- the endorsed terms: the invoice is restated from 1000000 to 1200000 -----
REPLACEMENT_NUMBER = "CERT-A2"
REPLACEMENT_INVOICE_VALUE = 1200000
# 1200000.00 invoice + 5000.00 duty + 45000.00 prepaid freight, uplifted 10%.
EXPECTED_REPLACEMENT_INSURED_VALUE = 1375000.00
# 1375.000 mille units at the 4.7250 marine rate, 0.6000 war, 0.255 strikes.
EXPECTED_REPLACEMENT_BASE_PREMIUM = 6496.88
EXPECTED_REPLACEMENT_WAR_PREMIUM = 825.00
EXPECTED_REPLACEMENT_STRIKES_PREMIUM = 350.63
EXPECTED_REPLACEMENT_TOTAL_PREMIUM = 7672.51
# Written premium is never reduced by a superseded row: 6444.91 + 7672.51.
EXPECTED_PREMIUM_BOOKED_AFTER_ENDORSEMENT = 14117.42

# --- the second shipment of the reinstatement scenario ----------------------
SAFE_DISCHARGE_NUMBER = "CERT-C"
SAFE_DECLARED_VALUE = 400000
# 400.000 mille units: 1890.00 marine + 240.00 war + 102.00 strikes.
EXPECTED_SAFE_TOTAL_PREMIUM = 2232.00

# --- the newly agreed war rate and what it charges the reinstated row -------
REINSTATEMENT_RATE_PER_MILLE = 0.400
EXPECTED_REINSTATEMENT_PREMIUM = 462.00
# 6444.91 + 2232.00 written at issue, plus the 462.00 reinstatement premium.
EXPECTED_PREMIUM_BOOKED_AFTER_REINSTATEMENT = 9138.91

# --- clock instants the recipes need ---------------------------------------
POST_ATTACHMENT_CLOCK = "2026-08-15T00:00:00Z"
TIME_BAR_INSTANT = "2027-09-05T00:00:00Z"


# ---------------------------------------------------------------------------
# Composite states these scenarios need beyond the shared builders
# ---------------------------------------------------------------------------
def _rows_of(api: ApiClient, certificate_id: str, expected_count: int,
             status: Optional[str] = None) -> List[JsonDict]:
    """
    List the accumulation ledger rows of one certificate, optionally narrowed by
    ledger status, and assert how many rows match.
    """
    params = {"certificate_id": certificate_id}
    if status is not None:
        params["status"] = status
    response = api.list_accumulation_entries(UNDERWRITER, params)
    return assert_total_count(response, expected_count,
                              f"accumulation rows of {certificate_id}")


def _build_unapproved_hull_environment(api: ApiClient) -> JsonDict:
    """
    The canonical book of business plus two hulls that may not carry risk: one
    on no classification society at all, screened into its refusal, and one
    classed hull that was never submitted for screening. A shipment is declared
    on each, and the open cover's version is captured for the issue attempts.
    """
    env = build_canonical_environment(api)
    env["blocked_vessel"] = create_vessel(
        api, VESSEL_COMET, name="MV Rust",
        classification_society="UNCLASSED", flag_code="PA")
    env["unscreened_vessel"] = create_vessel(
        api, VESSEL_OLD_SALT, review=False, name="MV Fresh", year_built=2015)
    env["blocked_draft"] = build_draft_certificate(
        api, env, certificate_number="CERT-RUST",
        vessel_id=env["blocked_vessel"]["id"])
    env["unscreened_draft"] = build_draft_certificate(
        api, env, certificate_number="CERT-FRESH",
        vessel_id=env["unscreened_vessel"]["id"])
    env["policy_version"] = policy_version(api, env["policy_id"])
    return env


def _build_endorsed_environment(api: ApiClient) -> JsonDict:
    """
    One issued CIF certificate — insured 1155000.00, premium 6444.91 — endorsed
    onto a restated invoice of 1200000.00 under a fresh certificate number. No
    premium declaration exists, so the unreported precondition holds.
    """
    env = build_environment_with_issued_certificate(api)
    env["endorse_response"] = api.endorse_certificate(
        env["certificate_id"],
        {"certificate_number": REPLACEMENT_NUMBER,
         "invoice_value": REPLACEMENT_INVOICE_VALUE},
        UNDERWRITER)
    env["replacement"] = get_success_data(env["endorse_response"])
    env["replacement_id"] = env["replacement"]["id"]
    return env


def _build_war_reinstatement_environment(api: ApiClient) -> JsonDict:
    """
    Two certificates issued on one hull: one discharging at Rotterdam and one
    discharging at New York. Rotterdam is listed — terminating the cover's war
    axis and the Rotterdam certificate's — and then dropped back to amber, so
    the cover may be reinstated at a newly agreed 0.400 per mille.
    """
    env = build_canonical_environment(api)
    env["safe_port"] = create_port(api, PORT_USNYC)
    env["certificate_a"] = build_issued_certificate(api, env)
    env["certificate_a_id"] = env["certificate_a"]["id"]
    env["certificate_c"] = build_issued_certificate(
        api, env, base=CERTIFICATE_DECLARED_SHIPMENT,
        certificate_number=SAFE_DISCHARGE_NUMBER,
        declared_value=SAFE_DECLARED_VALUE,
        package_count=40, gross_weight_kg=6000,
        discharge_port_id=env["safe_port"]["id"])
    env["certificate_c_id"] = env["certificate_c"]["id"]
    get_success_data(api.set_port_war_risk_tier(
        env["discharge_port_id"], {"war_risk_tier": "LISTED_AREA"},
        COMPLIANCE_OFFICER))
    get_success_data(api.set_port_war_risk_tier(
        env["discharge_port_id"], {"war_risk_tier": "AMBER"},
        COMPLIANCE_OFFICER))
    env["reinstatement"] = get_success_data(api.reinstate_war_cover(
        env["policy_id"],
        {"reinstatement_rate_per_mille": REINSTATEMENT_RATE_PER_MILLE},
        COMPLIANCE_OFFICER))
    return env


def _build_time_barred_notice(api: ApiClient) -> JsonDict:
    """
    An adjusted claim on the canonical certificate — 12.5 percent damage on
    1155000.00 behind a 2500.00 excess — with the logical clock moved to exactly
    the pinned time bar and a notice served against the carrier at that instant.
    """
    env = build_adjusted_claim(api)
    set_clock(api, TIME_BAR_INSTANT)
    env["notice_response"] = api.send_subrogation_notice(
        env["claim_id"], {"carrier_name": "Ocean Lines SA"}, CLAIMS_ADJUSTER_2)
    return env


# ---------------------------------------------------------------------------
# Activating an open cover
# ---------------------------------------------------------------------------
def test_activation_moves_the_status_axis_and_leaves_the_war_axis_attached(
        api: ApiClient) -> None:
    """
    Activation carries the contractual axis to ACTIVE and no other axis with it.

    Activating a policy moves its `status` from `DRAFT` to `ACTIVE` and leaves `war_cover_status` exactly where it was, at `ATTACHED`.

    Design: Corner/state_machines/open_policy_activation_moves_status_only_and_leaves_war_axis_attached
    """
    policy = create_open_policy(api, activate=False)
    assert policy["status"] == "DRAFT", "a newly written cover is not DRAFT"
    assert policy["war_cover_status"] == "ATTACHED"
    assert policy["version"] == 1

    activated = validate_success(
        api.activate_open_policy(policy["id"], UNDERWRITER))
    assert activated["status"] == "ACTIVE", (
        f"expected ACTIVE, got {activated['status']}"
    )
    assert activated["war_cover_status"] == "ATTACHED", (
        "activation moved the war axis: "
        f"{activated['war_cover_status']}"
    )
    assert activated["version"] == 2, (
        f"activation must increment the version, got {activated['version']}"
    )


def test_activation_books_no_risk_on_any_of_the_five_policy_ledgers(
        api: ApiClient) -> None:
    """
    Activation is not certificate activity, so every cover ledger stays at zero.

    A policy carries five of them — `aggregate_insured_value_booked`, `aggregate_premium_booked`, `aggregate_return_premium`, `security_deposit_held_amount` and `certificates_issued_count` — all initialised to zero when the policy is written and all moved only as a consequence of certificate, declaration or general average activity.

    Design: Corner/state_machines/open_policy_activation_moves_status_only_and_leaves_war_axis_attached
    """
    policy = create_open_policy(api, activate=False)
    activated = validate_success(
        api.activate_open_policy(policy["id"], UNDERWRITER))

    assert_money(activated["aggregate_insured_value_booked"], 0.00,
                 "policy.aggregate_insured_value_booked")
    assert_money(activated["aggregate_premium_booked"], 0.00,
                 "policy.aggregate_premium_booked")
    assert_money(activated["aggregate_return_premium"], 0.00,
                 "policy.aggregate_return_premium")
    assert_money(activated["security_deposit_held_amount"], 0.00,
                 "policy.security_deposit_held_amount")
    assert activated["certificates_issued_count"] == 0, (
        "activation booked a certificate: "
        f"{activated['certificates_issued_count']}"
    )


def test_activating_an_already_active_open_cover_is_an_invalid_state(
        api: ApiClient) -> None:
    """
    ACTIVE is not a from-state of activation, and the refusal writes nothing.

    Activation by an `Underwriter` moves `DRAFT → ACTIVE` and is refused unless the policy is currently `DRAFT`, `expiry_at` is strictly later than `inception_at`, `conveyance_limit_amount` is at least `per_certificate_limit_amount`, and `annual_aggregate_limit_amount` is at least `conveyance_limit_amount`; a failure on any of those reports `ERR_INVALID_STATE`.

    Design: Corner/state_machines/open_policy_activate_from_active_returns_invalid_state
    """
    policy = create_open_policy(api)
    assert policy["status"] == "ACTIVE"

    validate_error(api.activate_open_policy(policy["id"], UNDERWRITER),
                   ERR_INVALID_STATE)

    after = read_policy(api, policy["id"])
    assert after["status"] == "ACTIVE", (
        f"the refused activate moved the status to {after['status']}"
    )
    assert after["version"] == 2, (
        f"the refused activate bumped the version to {after['version']}"
    )


# ---------------------------------------------------------------------------
# Declaring a shipment: both certificate axes start at their initial state
# ---------------------------------------------------------------------------
def test_declared_shipment_starts_draft_with_a_pending_war_axis(
        api: ApiClient, canonical_env: JsonDict) -> None:
    """
    A shipment declaration lands on the initial state of both certificate axes.

    A successful declaration creates the certificate in `status` `DRAFT` with `war_cover_status` `PENDING`.

    Design: Corner/state_machines/certificate_creation_starts_in_draft_with_pending_war_axis_and_no_exposure
    """
    draft = build_draft_certificate(api, canonical_env)

    assert draft["status"] == "DRAFT", (
        f"expected DRAFT, got {draft['status']}"
    )
    assert draft["war_cover_status"] == "PENDING", (
        f"expected a PENDING war axis, got {draft['war_cover_status']}"
    )
    assert draft["version"] == 1, (
        f"a freshly created row starts at version 1, got {draft['version']}"
    )


def test_declared_shipment_previews_its_insured_value_and_pins_the_excess(
        api: ApiClient, canonical_env: JsonDict) -> None:
    """
    The draft carries a valued preview and the cover's excess copied onto it.

    The insured value is previewed onto the draft row using the variant named by `valuation_basis`, and the excess is pinned: `deductible_amount` on the certificate is copied from the policy's `deductible_amount` at this moment and belongs to the certificate thereafter.

    Design: Corner/state_machines/certificate_creation_starts_in_draft_with_pending_war_axis_and_no_exposure
    """
    draft = build_draft_certificate(api, canonical_env)

    assert_money(draft["insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "certificate.insured_value")
    assert_money(draft["deductible_amount"], POLICY_DEDUCTIBLE,
                 "certificate.deductible_amount")


def test_declared_shipment_books_no_exposure_and_no_premium(
        api: ApiClient, canonical_env: JsonDict) -> None:
    """
    Nothing is booked until issue: no ledger row, no premium, no cover window.

    A draft certificate carries no exposure at all — not one accumulation ledger is touched, `insured_value` is a preview rather than a booking, and `attachment_at`, `transit_termination_at`, `effective_rate_per_mille`, the four premium fields, `issued_by_user_id` and `issued_at` are all still null.

    Design: Corner/state_machines/certificate_creation_starts_in_draft_with_pending_war_axis_and_no_exposure
    """
    draft = build_draft_certificate(api, canonical_env)

    _rows_of(api, draft["id"], 0)

    for field in ("attachment_at", "transit_termination_at",
                  "effective_rate_per_mille", "base_premium_amount",
                  "war_premium_amount", "strikes_premium_amount",
                  "total_premium_amount", "issued_by_user_id", "issued_at"):
        assert draft.get(field) is None, (
            f"certificate.{field} must be null on a draft, got {draft.get(field)}"
        )

    vessel = read_vessel(api, canonical_env["vessel_id"])
    assert_money(vessel["accumulated_insured_value"], 0.00,
                 "vessel.accumulated_insured_value")
    for port_id in (canonical_env["loading_port_id"],
                    canonical_env["discharge_port_id"]):
        port = validate_success(api.get_port(port_id, UNDERWRITER))
        assert_money(port["accumulated_insured_value"], 0.00,
                     "port.accumulated_insured_value")
    policy = read_policy(api, canonical_env["policy_id"])
    assert_money(policy["aggregate_insured_value_booked"], 0.00,
                 "policy.aggregate_insured_value_booked")


# ---------------------------------------------------------------------------
# Issuing twice: the state, not the version, refuses the second booking
# ---------------------------------------------------------------------------
def test_repeated_issue_is_refused_as_an_invalid_state(
        api: ApiClient, issued_certificate_env: JsonDict) -> None:
    """
    An issued certificate has no issue transition left, even at a current version.

    When a triggered action has no transition whose `from` state matches the resource's current state field, or when a non-cross-entity precondition of that transition fails, the answer is `ERR_INVALID_STATE` (HTTP 409).

    Design: Corner/state_machines/certificate_issue_repeated_returns_invalid_state_not_a_second_booking
    """
    env = issued_certificate_env
    current_version = policy_version(api, env["policy_id"])

    validate_error(
        api.issue_certificate(
            env["certificate_id"],
            {"expected_open_policy_version": current_version}, UNDERWRITER),
        ERR_INVALID_STATE)

    certificate = read_certificate(api, env["certificate_id"])
    assert certificate["status"] == "ISSUED", (
        f"the refused issue moved the status to {certificate['status']}"
    )
    assert_money(certificate["total_premium_amount"], EXPECTED_TOTAL_PREMIUM,
                 "certificate.total_premium_amount")


def test_repeated_issue_leaves_the_cover_ledgers_at_a_single_booking(
        api: ApiClient, issued_certificate_env: JsonDict) -> None:
    """
    One issue books once: the refused second issue moves no cover ledger.

    On the policy, `aggregate_insured_value_booked` rises by the insured value, `aggregate_premium_booked` rises by the total premium, and `certificates_issued_count` increments by one — that counter records every certificate that has ever left `DRAFT`, so it never falls back when one is later cancelled.

    Design: Corner/state_machines/certificate_issue_repeated_returns_invalid_state_not_a_second_booking
    """
    env = issued_certificate_env
    current_version = policy_version(api, env["policy_id"])

    validate_error(
        api.issue_certificate(
            env["certificate_id"],
            {"expected_open_policy_version": current_version}, UNDERWRITER),
        ERR_INVALID_STATE)

    policy = read_policy(api, env["policy_id"])
    assert_money(policy["aggregate_insured_value_booked"],
                 EXPECTED_INSURED_VALUE_CIF,
                 "policy.aggregate_insured_value_booked")
    assert_money(policy["aggregate_premium_booked"], EXPECTED_TOTAL_PREMIUM,
                 "policy.aggregate_premium_booked")
    assert policy["certificates_issued_count"] == 1, (
        "the refused issue counted a second certificate: "
        f"{policy['certificates_issued_count']}"
    )
    assert policy["version"] == current_version, (
        f"the refused issue bumped the cover version to {policy['version']}"
    )


def test_repeated_issue_leaves_exactly_three_active_ledger_rows(
        api: ApiClient, issued_certificate_env: JsonDict) -> None:
    """
    The certificate keeps the three ledger rows its single issue created.

    Three accumulation ledger rows are created in `status` `ACTIVE`, each with `amount` equal to the certificate's insured value at this instant and `release_reason` `NONE`: one of `scope_type` `VESSEL` carrying `vessel_id`, one of `scope_type` `LOADING_PORT` carrying the loading `port_id`, and one of `scope_type` `DISCHARGE_PORT` carrying the discharge `port_id`.

    Design: Corner/state_machines/certificate_issue_repeated_returns_invalid_state_not_a_second_booking
    """
    env = issued_certificate_env
    current_version = policy_version(api, env["policy_id"])

    validate_error(
        api.issue_certificate(
            env["certificate_id"],
            {"expected_open_policy_version": current_version}, UNDERWRITER),
        ERR_INVALID_STATE)

    rows = _rows_of(api, env["certificate_id"], 3, status="ACTIVE")
    for scope_type in ("VESSEL", "LOADING_PORT", "DISCHARGE_PORT"):
        row = find_row(rows, scope_type=scope_type)
        assert_money(row["amount"], EXPECTED_INSURED_VALUE_CIF,
                     f"{scope_type} row amount")
        assert row["release_reason"] == "NONE", (
            f"{scope_type} row carries release_reason {row['release_reason']}"
        )


# ---------------------------------------------------------------------------
# A cancelled certificate is locked down
# ---------------------------------------------------------------------------
def test_second_cancel_of_a_cancelled_certificate_is_already_terminal(
        api: ApiClient) -> None:
    """
    Cancelling twice reports the terminal fault, not a plain state mismatch.

    When the state field being targeted already sits in one of its machine's terminal states — `ACCEPTED` on a declaration, `SETTLED` or `DENIED` on a claim, `RECOVERED` or `TIME_BARRED` on a subrogation axis, `ADJUSTED` on a general average event, `RELEASED` on a security posting or accumulation entry, `REPORT_FILED` or `CANCELLED` on a survey order, `EXPIRED` or `CANCELLED` on a policy, `SUPERSEDED`, `CANCELLED` or `TRANSIT_ENDED` on a certificate, `NOT_TAKEN` on a certificate's war axis — the answer is `ERR_ALREADY_TERMINAL` (HTTP 409).

    Design: Corner/state_machines/cancelled_certificate_rejects_further_triggers_with_already_terminal
    """
    env = build_cancelled_certificate(api)
    assert env["certificate"]["status"] == "CANCELLED"

    validate_error(
        api.cancel_certificate(env["certificate_id"], UNDERWRITER,
                               {"cancellation_reason": "duplicate cancel attempt"}),
        ERR_ALREADY_TERMINAL)

    certificate = read_certificate(api, env["certificate_id"])
    assert certificate["status"] == "CANCELLED", (
        f"the refused cancel moved the status to {certificate['status']}"
    )


def test_confirm_delivery_on_a_cancelled_certificate_is_already_terminal(
        api: ApiClient) -> None:
    """
    No trigger escapes a terminal certificate, not even the assured's delivery.

    When the state field being targeted already sits in one of its machine's terminal states — `ACCEPTED` on a declaration, `SETTLED` or `DENIED` on a claim, `RECOVERED` or `TIME_BARRED` on a subrogation axis, `ADJUSTED` on a general average event, `RELEASED` on a security posting or accumulation entry, `REPORT_FILED` or `CANCELLED` on a survey order, `EXPIRED` or `CANCELLED` on a policy, `SUPERSEDED`, `CANCELLED` or `TRANSIT_ENDED` on a certificate, `NOT_TAKEN` on a certificate's war axis — the answer is `ERR_ALREADY_TERMINAL` (HTTP 409).

    Design: Corner/state_machines/cancelled_certificate_rejects_further_triggers_with_already_terminal
    """
    env = build_cancelled_certificate(api)
    # Move the clock past the pinned attachment instant so the only failing
    # precondition left on confirm-delivery is the certificate's terminal state.
    set_clock(api, POST_ATTACHMENT_CLOCK)

    validate_error(
        api.confirm_delivery(env["certificate_id"],
                             make_assured_headers(env["policy_id"]),
                             {"delivered_at": POST_ATTACHMENT_CLOCK}),
        ERR_ALREADY_TERMINAL)

    certificate = read_certificate(api, env["certificate_id"])
    assert certificate["status"] == "CANCELLED", (
        f"confirm-delivery moved a terminal row to {certificate['status']}"
    )


def test_pre_attachment_cancellation_returns_the_whole_premium_exactly_once(
        api: ApiClient) -> None:
    """
    The unearned return is computed on the unreturned remainder, so it books once.

    The system takes the certificate's `total_premium_amount` plus its `reinstatement_premium_amount`, subtracts the `return_premium_amount` already booked on it, multiplies the remainder by the applicable unearned percentage, and rounds the product half up to 2 decimals; that amount is added to `return_premium_amount` and the same amount is added to the policy's `aggregate_return_premium`.

    Design: Corner/state_machines/cancelled_certificate_rejects_further_triggers_with_already_terminal
    """
    env = build_cancelled_certificate(api)
    assert_money(env["certificate"]["return_premium_amount"],
                 EXPECTED_TOTAL_PREMIUM, "certificate.return_premium_amount")

    validate_error(
        api.cancel_certificate(env["certificate_id"], UNDERWRITER,
                               {"cancellation_reason": "duplicate cancel attempt"}),
        ERR_ALREADY_TERMINAL)

    certificate = read_certificate(api, env["certificate_id"])
    assert_money(certificate["return_premium_amount"], EXPECTED_TOTAL_PREMIUM,
                 "certificate.return_premium_amount after a refused cancel")
    policy = read_policy(api, env["policy_id"])
    assert_money(policy["aggregate_return_premium"], EXPECTED_TOTAL_PREMIUM,
                 "policy.aggregate_return_premium")


def test_cancellation_releases_all_three_ledger_rows_and_restores_the_ledgers(
        api: ApiClient) -> None:
    """
    Cancellation is a compensating movement on every ledger the issue touched.

    On success the certificate goes `ISSUED → CANCELLED`, its `ACTIVE` accumulation rows become `RELEASED` with `release_reason` `CERTIFICATE_CANCELLED`, the vessel and both port ledgers fall by exactly what they rose by at issue, the policy's `aggregate_insured_value_booked` falls by the insured value, and the policy's `version` increments.

    Design: Corner/state_machines/cancelled_certificate_rejects_further_triggers_with_already_terminal
    """
    env = build_cancelled_certificate(api)

    rows = _rows_of(api, env["certificate_id"], 3)
    for row in rows:
        assert row["status"] == "RELEASED", (
            f"{row['scope_type']} row is still {row['status']}"
        )
        assert row["release_reason"] == "CERTIFICATE_CANCELLED", (
            f"{row['scope_type']} row released for {row['release_reason']}"
        )

    vessel = read_vessel(api, env["vessel_id"])
    assert_money(vessel["accumulated_insured_value"], 0.00,
                 "vessel.accumulated_insured_value")
    for port_id in (env["loading_port_id"], env["discharge_port_id"]):
        port = validate_success(api.get_port(port_id, UNDERWRITER))
        assert_money(port["accumulated_insured_value"], 0.00,
                     "port.accumulated_insured_value")
    policy = read_policy(api, env["policy_id"])
    assert_money(policy["aggregate_insured_value_booked"], 0.00,
                 "policy.aggregate_insured_value_booked")


# ---------------------------------------------------------------------------
# Hulls that may not carry risk
# ---------------------------------------------------------------------------
def test_unclassed_hull_screens_straight_to_blocked_at_any_age(
        api: ApiClient) -> None:
    """
    A hull on no classification society is refused whatever its build year.

    If the society is `UNCLASSED` the vessel goes to `BLOCKED` with `overage_surcharge_pct` set to 0, at any age — a two-year-old ship on no class is still uninsurable.

    Design: Corner/state_machines/unscreened_and_unclassed_hulls_are_refused_at_issue
    """
    hull = create_vessel(api, VESSEL_COMET, name="MV Rust",
                         classification_society="UNCLASSED", flag_code="PA")

    assert hull["status"] == "BLOCKED", (
        f"an unclassed hull screened to {hull['status']}"
    )
    assert_rate(hull["overage_surcharge_pct"], 0.00, places=2,
                label="vessel.overage_surcharge_pct")


def test_issue_on_a_blocked_hull_is_refused_before_any_capacity_arithmetic(
        api: ApiClient) -> None:
    """
    The hull screen stands between an unclassed conveyance and a booked risk.

    Then the hull: the nominated vessel must be `APPROVED` or `OVERAGE_SURCHARGED`, and a vessel that is `BLOCKED`, still `PENDING_REVIEW` or in `GA_HOLD` gives `ERR_VESSEL_BLOCKED` (HTTP 422) — refused before any capacity arithmetic is attempted.

    Design: Corner/state_machines/unscreened_and_unclassed_hulls_are_refused_at_issue
    """
    env = _build_unapproved_hull_environment(api)

    validate_error(
        api.issue_certificate(
            env["blocked_draft"]["id"],
            {"expected_open_policy_version": env["policy_version"]},
            UNDERWRITER),
        ERR_VESSEL_BLOCKED)

    certificate = read_certificate(api, env["blocked_draft"]["id"])
    assert certificate["status"] == "DRAFT", (
        f"the refused issue moved the certificate to {certificate['status']}"
    )
    policy = read_policy(api, env["policy_id"])
    assert_money(policy["aggregate_insured_value_booked"], 0.00,
                 "policy.aggregate_insured_value_booked")
    assert policy["certificates_issued_count"] == 0, (
        f"the refused issue counted {policy['certificates_issued_count']}"
    )
    assert policy["version"] == env["policy_version"], (
        f"the refused issue bumped the cover version to {policy['version']}"
    )


def test_issue_on_a_hull_never_submitted_for_screening_is_refused(
        api: ApiClient) -> None:
    """
    An unscreened hull is refused on the very same rule as a blocked one.

    Then the hull: the nominated vessel must be `APPROVED` or `OVERAGE_SURCHARGED`, and a vessel that is `BLOCKED`, still `PENDING_REVIEW` or in `GA_HOLD` gives `ERR_VESSEL_BLOCKED` (HTTP 422) — refused before any capacity arithmetic is attempted.

    Design: Corner/state_machines/unscreened_and_unclassed_hulls_are_refused_at_issue
    """
    env = _build_unapproved_hull_environment(api)
    hull = read_vessel(api, env["unscreened_vessel"]["id"])
    assert hull["status"] == "PENDING_REVIEW", (
        f"the unscreened hull sits at {hull['status']}"
    )

    validate_error(
        api.issue_certificate(
            env["unscreened_draft"]["id"],
            {"expected_open_policy_version": env["policy_version"]},
            UNDERWRITER),
        ERR_VESSEL_BLOCKED)

    certificate = read_certificate(api, env["unscreened_draft"]["id"])
    assert certificate["status"] == "DRAFT", (
        f"the refused issue moved the certificate to {certificate['status']}"
    )
    policy = read_policy(api, env["policy_id"])
    assert_money(policy["aggregate_insured_value_booked"], 0.00,
                 "policy.aggregate_insured_value_booked")


# ---------------------------------------------------------------------------
# Endorsement: the original is superseded and the replacement is repriced
# ---------------------------------------------------------------------------
def test_endorsement_supersedes_the_original_and_returns_its_premium_in_full(
        api: ApiClient) -> None:
    """
    The endorsed row leaves the ISSUED state and gives back everything it charged.

    The original certificate goes `ISSUED → SUPERSEDED`, and because the replacement stands in its place from inception, the original's premium is returned in full *ab initio*: its `return_premium_amount` rises by its own `total_premium_amount` plus its `reinstatement_premium_amount`.

    Design: Corner/state_machines/certificate_endorsement_supersedes_original_and_reprices_replacement
    """
    env = _build_endorsed_environment(api)

    original = read_certificate(api, env["certificate_id"])
    assert original["status"] == "SUPERSEDED", (
        f"the endorsed original sits at {original['status']}"
    )
    assert_money(original["return_premium_amount"], EXPECTED_TOTAL_PREMIUM,
                 "original.return_premium_amount")


def test_endorsement_creates_the_replacement_directly_in_issued(
        api: ApiClient) -> None:
    """
    The replacement is a new resource that never passes through DRAFT.

    A new certificate is then created directly in `status` `ISSUED` — it never passes through `DRAFT` — carrying `replaces_certificate_id` pointing at the superseded row, the supplied certificate number, a freshly computed insured value, a freshly composed set of premium components, its own pinned attachment and transit-termination instants, and its own three fresh `ACTIVE` accumulation rows with their own ledger increases.

    Design: Corner/state_machines/certificate_endorsement_supersedes_original_and_reprices_replacement
    """
    env = _build_endorsed_environment(api)
    replacement = validate_success(env["endorse_response"], 201)

    assert replacement["status"] == "ISSUED", (
        f"the replacement was created in {replacement['status']}"
    )
    assert replacement["replaces_certificate_id"] == env["certificate_id"], (
        "replaces_certificate_id points at "
        f"{replacement['replaces_certificate_id']}"
    )
    assert replacement["certificate_number"] == REPLACEMENT_NUMBER
    assert replacement["id"] != env["certificate_id"], (
        "endorsement modified the original instead of minting a replacement"
    )
    assert replacement["attachment_at"] is not None
    assert replacement["transit_termination_at"] is not None
    _rows_of(api, env["replacement_id"], 3, status="ACTIVE")


def test_endorsement_recomputes_the_replacement_insured_value(
        api: ApiClient) -> None:
    """
    The restated invoice is revalued with the freight, the duty and the markup.

    The insured value is then the CIF base multiplied by one plus the policy's `markup_pct`, and that product is rounded half up to 2 decimals — one rounding, at the very end, never a rounding of the base first.

    Design: Corner/state_machines/certificate_endorsement_supersedes_original_and_reprices_replacement
    """
    env = _build_endorsed_environment(api)

    replacement = read_certificate(api, env["replacement_id"])
    assert_money(replacement["insured_value"],
                 EXPECTED_REPLACEMENT_INSURED_VALUE,
                 "replacement.insured_value")


def test_endorsement_recomposes_the_replacement_premium_components(
        api: ApiClient) -> None:
    """
    Each component of the replacement's premium is rounded before they are summed.

    `total_premium_amount` is then the sum of those three already-rounded components — never a re-derivation from the unrounded figures, and never recomputed after issue.

    Design: Corner/state_machines/certificate_endorsement_supersedes_original_and_reprices_replacement
    """
    env = _build_endorsed_environment(api)

    replacement = read_certificate(api, env["replacement_id"])
    assert_money(replacement["base_premium_amount"],
                 EXPECTED_REPLACEMENT_BASE_PREMIUM,
                 "replacement.base_premium_amount")
    assert_money(replacement["war_premium_amount"],
                 EXPECTED_REPLACEMENT_WAR_PREMIUM,
                 "replacement.war_premium_amount")
    assert_money(replacement["strikes_premium_amount"],
                 EXPECTED_REPLACEMENT_STRIKES_PREMIUM,
                 "replacement.strikes_premium_amount")
    assert_money(replacement["total_premium_amount"],
                 EXPECTED_REPLACEMENT_TOTAL_PREMIUM,
                 "replacement.total_premium_amount")


def test_endorsement_releases_the_original_rows_and_leaves_one_exposure(
        api: ApiClient) -> None:
    """
    The superseded exposure is given back, so the hull carries the new line only.

    All of its `ACTIVE` accumulation rows become `RELEASED` with `release_reason` `CERTIFICATE_SUPERSEDED`, and the vessel and both port `accumulated_insured_value` ledgers fall by the released amounts.

    Design: Corner/state_machines/certificate_endorsement_supersedes_original_and_reprices_replacement
    """
    env = _build_endorsed_environment(api)

    released = _rows_of(api, env["certificate_id"], 3)
    for row in released:
        assert row["status"] == "RELEASED", (
            f"{row['scope_type']} row of the original is still {row['status']}"
        )
        assert row["release_reason"] == "CERTIFICATE_SUPERSEDED", (
            f"{row['scope_type']} row released for {row['release_reason']}"
        )

    fresh = _rows_of(api, env["replacement_id"], 3, status="ACTIVE")
    for row in fresh:
        assert_money(row["amount"], EXPECTED_REPLACEMENT_INSURED_VALUE,
                     f"{row['scope_type']} row amount")

    vessel = read_vessel(api, env["vessel_id"])
    assert_money(vessel["accumulated_insured_value"],
                 EXPECTED_REPLACEMENT_INSURED_VALUE,
                 "vessel.accumulated_insured_value")
    for port_id in (env["loading_port_id"], env["discharge_port_id"]):
        port = validate_success(api.get_port(port_id, UNDERWRITER))
        assert_money(port["accumulated_insured_value"],
                     EXPECTED_REPLACEMENT_INSURED_VALUE,
                     "port.accumulated_insured_value")


def test_endorsement_moves_the_three_cover_ledgers_on_their_own_bases(
        api: ApiClient) -> None:
    """
    Written premium accumulates, returned premium accumulates, exposure nets off.

    On the policy, `aggregate_return_premium` rises by the return just booked, `aggregate_premium_booked` rises by the replacement's `total_premium_amount` (it is never reduced by the superseded row's premium — written and returned premium live on separate ledgers), and `aggregate_insured_value_booked` moves by the difference between the replacement's insured value and the original's.

    Design: Corner/state_machines/certificate_endorsement_supersedes_original_and_reprices_replacement
    """
    env = _build_endorsed_environment(api)

    policy = read_policy(api, env["policy_id"])
    assert_money(policy["aggregate_return_premium"], EXPECTED_TOTAL_PREMIUM,
                 "policy.aggregate_return_premium")
    assert_money(policy["aggregate_premium_booked"],
                 EXPECTED_PREMIUM_BOOKED_AFTER_ENDORSEMENT,
                 "policy.aggregate_premium_booked")
    assert_money(policy["aggregate_insured_value_booked"],
                 EXPECTED_REPLACEMENT_INSURED_VALUE,
                 "policy.aggregate_insured_value_booked")


# ---------------------------------------------------------------------------
# War cover: termination by listing, then reinstatement at a new rate
# ---------------------------------------------------------------------------
def test_reinstatement_moves_the_cover_war_axis_and_clears_the_audit_fields(
        api: ApiClient) -> None:
    """
    Reinstating war cover stores the newly agreed rate and forgets the listing.

    On success the policy's war axis moves `TERMINATED → REINSTATED`, the supplied rate is stored in `reinstatement_rate_per_mille`, and both `war_terminated_at` and `war_termination_port_unlocode` are cleared to null.

    Design: Corner/state_machines/war_cover_reinstatement_reprices_only_the_terminated_certificate
    """
    env = _build_war_reinstatement_environment(api)

    policy = read_policy(api, env["policy_id"])
    assert policy["war_cover_status"] == "REINSTATED", (
        f"the cover's war axis sits at {policy['war_cover_status']}"
    )
    assert_rate(policy["reinstatement_rate_per_mille"],
                REINSTATEMENT_RATE_PER_MILLE, places=3,
                label="policy.reinstatement_rate_per_mille")
    assert policy["war_terminated_at"] is None, (
        f"war_terminated_at survived reinstatement: {policy['war_terminated_at']}"
    )
    assert policy["war_termination_port_unlocode"] is None, (
        "war_termination_port_unlocode survived reinstatement: "
        f"{policy['war_termination_port_unlocode']}"
    )


def test_reinstatement_reprices_only_the_terminated_certificate(
        api: ApiClient) -> None:
    """
    Only a certificate whose own war axis fell away is examined and recharged.

    Every certificate on the policy whose `status` is `ISSUED` and whose `war_cover_status` is `TERMINATED` is examined; if neither its loading port nor its discharge port is in tier `LISTED_AREA` at that instant, its war axis moves `TERMINATED → REINSTATED` and it is charged additional premium: its `reinstatement_premium_amount` is set to its insured value divided by 1000, multiplied by the policy's newly agreed reinstatement rate per mille, rounded half up to 2 decimals.

    Design: Corner/state_machines/war_cover_reinstatement_reprices_only_the_terminated_certificate
    """
    env = _build_war_reinstatement_environment(api)

    exposed = read_certificate(api, env["certificate_a_id"])
    assert exposed["war_cover_status"] == "REINSTATED", (
        f"the exposed certificate sits at {exposed['war_cover_status']}"
    )
    assert_money(exposed["reinstatement_premium_amount"],
                 EXPECTED_REINSTATEMENT_PREMIUM,
                 "exposed certificate.reinstatement_premium_amount")

    untouched = read_certificate(api, env["certificate_c_id"])
    assert untouched["war_cover_status"] == "ATTACHED", (
        "the certificate that never touched the listed port sits at "
        f"{untouched['war_cover_status']}"
    )
    assert_money(untouched["reinstatement_premium_amount"], 0.00,
                 "untouched certificate.reinstatement_premium_amount")


def test_reinstatement_books_only_the_premiums_actually_charged(
        api: ApiClient) -> None:
    """
    The cover's written premium rises by the one reinstatement premium booked.

    The policy's `aggregate_premium_booked` rises by the sum of the reinstatement premiums actually booked, and every certificate that moved has its `version` incremented.

    Design: Corner/state_machines/war_cover_reinstatement_reprices_only_the_terminated_certificate
    """
    env = _build_war_reinstatement_environment(api)

    policy = read_policy(api, env["policy_id"])
    assert_money(policy["aggregate_premium_booked"],
                 EXPECTED_PREMIUM_BOOKED_AFTER_REINSTATEMENT,
                 "policy.aggregate_premium_booked")


def test_reinstatement_leaves_the_earlier_war_and_strikes_return_alone(
        api: ApiClient) -> None:
    """
    What came back when the port was listed stays returned after reinstatement.

    A certificate coming from `ATTACHED` has its `return_premium_amount` increased by its `war_premium_amount` plus its `strikes_premium_amount` — both components return in full, because both were sold against a geography that no longer exists.

    Design: Corner/state_machines/war_cover_reinstatement_reprices_only_the_terminated_certificate
    """
    env = _build_war_reinstatement_environment(api)

    exposed = read_certificate(api, env["certificate_a_id"])
    assert_money(exposed["war_premium_amount"], EXPECTED_WAR_PREMIUM,
                 "certificate.war_premium_amount")
    assert_money(exposed["strikes_premium_amount"], EXPECTED_STRIKES_PREMIUM,
                 "certificate.strikes_premium_amount")
    assert_money(exposed["return_premium_amount"], EXPECTED_WAR_STRIKES_RETURN,
                 "certificate.return_premium_amount")


# ---------------------------------------------------------------------------
# Subrogation served at exactly the time bar
# ---------------------------------------------------------------------------
def test_adjustment_pins_the_time_bar_at_discharge_plus_a_year(
        api: ApiClient) -> None:
    """
    The carrier time bar is fixed when the claim is adjusted, from the discharge.

    The loss is quantified, `adjusted_by_user_id` records the acting `X-User-ID`, and `time_bar_at` is pinned to the certificate's `discharge_date` plus 365 days — one year from discharge, the conventional carrier time bar.

    Design: Corner/state_machines/subrogation_notice_at_the_time_bar_flips_the_axis_to_time_barred
    """
    env = build_adjusted_claim(api)
    claim = read_claim_file(api, env["claim_id"], CLAIMS_ADJUSTER_2)

    assert claim["status"] == "ADJUSTED", (
        f"the claim did not reach ADJUSTED, it sits at {claim['status']}"
    )
    assert claim["time_bar_at"] is not None, "time_bar_at was not pinned"
    assert claim["time_bar_at"].startswith("2027-09-05T00:00:00"), (
        f"time_bar_at is {claim['time_bar_at']}, not 365 days after discharge"
    )


def test_notice_served_at_the_time_bar_is_barred_and_flips_the_axis(
        api: ApiClient) -> None:
    """
    At the bar itself the notice fails and the recovery axis goes terminal anyway.

    At or after the time bar the attempt is barred: the axis flips to the terminal `TIME_BARRED`, no notice is recorded, the claim's `version` still increments so that the barred attempt leaves an audit trace, and the request itself fails with `ERR_SUBROGATION_TIME_BARRED` (HTTP 409).

    Design: Corner/state_machines/subrogation_notice_at_the_time_bar_flips_the_axis_to_time_barred
    """
    env = _build_time_barred_notice(api)

    validate_error(env["notice_response"], ERR_SUBROGATION_TIME_BARRED)

    claim = read_claim_file(api, env["claim_id"], CLAIMS_ADJUSTER_2)
    assert claim["subrogation_status"] == "TIME_BARRED", (
        f"the recovery axis sits at {claim['subrogation_status']}"
    )
    assert claim.get("carrier_name") is None, (
        f"a barred attempt recorded the carrier {claim.get('carrier_name')}"
    )
    assert claim.get("subrogation_notice_at") is None, (
        "a barred attempt recorded a notice instant: "
        f"{claim.get('subrogation_notice_at')}"
    )


def test_barred_recovery_axis_leaves_the_indemnity_axis_where_it_was(
        api: ApiClient) -> None:
    """
    The claim's own lifecycle does not move when the recovery axis is barred.

    The recovery axis runs independently of the claim's own lifecycle.

    Design: Corner/state_machines/subrogation_notice_at_the_time_bar_flips_the_axis_to_time_barred
    """
    env = _build_time_barred_notice(api)

    claim = read_claim_file(api, env["claim_id"], CLAIMS_ADJUSTER_2)
    assert claim["status"] == "ADJUSTED", (
        f"the barred notice moved the indemnity axis to {claim['status']}"
    )


def test_barred_claim_keeps_the_loss_it_was_adjusted_for(
        api: ApiClient) -> None:
    """
    The quantified loss and the absorbed excess survive the barred attempt.

    `adjusted_amount` is then the gross loss minus the deductible, floored at 0.00 so it can never go negative, and `deductible_applied_amount` is the lesser of the deductible and the gross loss — a deductible larger than the loss is only absorbed up to the loss.

    Design: Corner/state_machines/subrogation_notice_at_the_time_bar_flips_the_axis_to_time_barred
    """
    env = _build_time_barred_notice(api)

    claim = read_claim_file(api, env["claim_id"], CLAIMS_ADJUSTER_2)
    assert_money(claim["adjusted_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION, "claim.adjusted_amount")
    assert_money(claim["deductible_applied_amount"],
                 EXPECTED_CLAIM_DEDUCTIBLE_APPLIED,
                 "claim.deductible_applied_amount")
