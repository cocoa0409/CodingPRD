"""
Gates a resource inherits from another resource's state, and the two opposite
interval geometries this API uses for occupancy.

Covers the certificate whose issue waits on its open cover leaving suspension,
the general average claim whose settlement waits on the average being stated,
the surveyor calendar whose closed attendance windows are inflated by travel
time, and the discharge-port storage window whose half-open ends make an
abutting shipment free of the one before it.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
)

from test_helpers import (
    ADJUSTER_2_USER_ID,
    ADJUSTER_USER_ID,
    CERTIFICATE_DECLARED_SHIPMENT,
    CLAIMS_ADJUSTER,
    CLAIMS_ADJUSTER_2,
    ERR_GA_ADJUSTMENT_PENDING,
    ERR_POLICY_NOT_ACTIVE,
    ERR_PORT_ACCUMULATION_EXCEEDED,
    ERR_SURVEYOR_WINDOW_CONFLICT,
    EXPECTED_CLAIM_ADJUSTED_DEPRECIATION,
    EXPECTED_GA_CONTRIBUTION_LARGEST,
    EXPECTED_GA_CONTRIBUTION_SMALLER,
    EXPECTED_GA_DEPOSIT_LARGEST,
    EXPECTED_GA_DEPOSIT_SMALLER,
    EXPECTED_INSURED_VALUE_CIF,
    EXPECTED_TOTAL_PREMIUM,
    PORT_NLRTM,
    PORT_SGSIN,
    UNDERWRITER,
    VESSEL_KITE,
    ApiClient,
    JsonDict,
    adjust_claim_file,
    assert_instant,
    assert_money,
    assert_rate,
    assert_total_count,
    audit_declaration,
    build_canonical_environment,
    build_draft_certificate,
    build_environment_with_issued_certificate,
    build_ga_event_with_security_calls,
    build_issued_certificate,
    complete_claim_documents,
    create_declaration,
    create_survey_order,
    issue_certificate,
    open_claim_file,
    policy_version,
    post_ga_security,
    read_certificate,
    read_claim_file,
    read_ga_event,
    read_policy,
    read_port,
    read_surveyor,
    submit_declaration,
)

# ---------------------------------------------------------------------------
# The draft that waits out a suspension
# ---------------------------------------------------------------------------
# A second shipment declared while the cover was still ACTIVE, stated at an
# agreed 500000.00 so its insured value needs no valuation arithmetic.
PENDING_DRAFT_DECLARED_VALUE = 500000
PENDING_DRAFT_OVERRIDES = {
    "certificate_number": "CERT-J",
    "declared_value": PENDING_DRAFT_DECLARED_VALUE,
    "package_count": 50,
    "gross_weight_kg": 7000,
    "sailing_date": "2026-08-20T00:00:00Z",
    "discharge_date": "2026-09-18T00:00:00Z",
    "war_cover_requested": False,
    "strikes_cover_requested": False,
}

# 5000.00 reported against a computed 6444.91: a variance of -1444.91, which is
# 22.42 percent of the computed total and so over the ten-percent trigger.
UNDER_DECLARED_TOTAL = 5000.00
EXPECTED_UNDER_DECLARED_VARIANCE_PCT = 22.42
EXPECTED_AUDIT_ADJUSTMENT_AMOUNT = 1444.91

# 1155000.00 already booked plus the 500000.00 the freed draft brings.
EXPECTED_BOOKED_AFTER_BOTH_CERTIFICATES = 1655000.00


def _suspend_the_cover_holding_a_pending_draft(api: ApiClient) -> JsonDict:
    """
    One issued certificate of 6444.91 premium, a second shipment still in draft,
    and a reporting period submitted at 5000.00 and audited — which drives the
    open cover out of ACTIVE and leaves the draft stranded.
    """
    env = build_environment_with_issued_certificate(api)
    env["pending_draft"] = build_draft_certificate(
        api, env, base=CERTIFICATE_DECLARED_SHIPMENT, **PENDING_DRAFT_OVERRIDES)
    env["pending_draft_id"] = env["pending_draft"]["id"]
    env["declaration"] = create_declaration(api, env["policy_id"])
    env["declaration_id"] = env["declaration"]["id"]
    submit_declaration(api, env["declaration_id"], env["policy_id"],
                       UNDER_DECLARED_TOTAL)
    env["audited"] = audit_declaration(api, env["declaration_id"],
                                       "material under-declaration")
    return env


def test_draft_certificate_cannot_be_issued_while_its_open_cover_is_suspended(
        api: ApiClient) -> None:
    """
    A suspended open cover refuses to issue a draft that was perfectly issuable
    the moment before.

    The certificate must be `DRAFT` and its policy `ACTIVE`; a policy in any other state gives `ERR_POLICY_NOT_ACTIVE`.

    Design: Difficulty/cross_entity_state_dependency/certificate_issue_depends_on_open_policy_status
    """
    env = _suspend_the_cover_holding_a_pending_draft(api)

    declaration = env["audited"]
    assert_rate(declaration["variance_pct"],
                EXPECTED_UNDER_DECLARED_VARIANCE_PCT, places=2,
                label="declaration.variance_pct")
    assert_money(declaration["audit_adjustment_amount"],
                 EXPECTED_AUDIT_ADJUSTMENT_AMOUNT,
                 "declaration.audit_adjustment_amount")

    suspended = read_policy(api, env["policy_id"])
    assert suspended["status"] == "SUSPENDED", (
        f"expected the cover to be SUSPENDED, got {suspended['status']}"
    )

    refused = api.issue_certificate(
        env["pending_draft_id"],
        {"expected_open_policy_version": suspended["version"]},
        UNDERWRITER)
    validate_error(refused, ERR_POLICY_NOT_ACTIVE)

    stranded = read_certificate(api, env["pending_draft_id"])
    assert stranded["status"] == "DRAFT", (
        f"the refused certificate must stay DRAFT, got {stranded['status']}"
    )
    assert stranded["issued_at"] is None, "a refused issue must not stamp issued_at"


def test_the_same_draft_issues_once_a_corrected_report_restores_the_cover(
        api: ApiClient) -> None:
    """
    Nothing about the draft changes; the parent cover returning to ACTIVE is
    what lets the identical issue call through.

    If the parent policy is `SUSPENDED` and the recomputed variance percentage is at or under the 2.5 percent tolerance, the policy returns `SUSPENDED → ACTIVE` and its `version` increments — the suspension lifts on the strength of an accurate report, not on an auditor's discretion.

    Design: Difficulty/cross_entity_state_dependency/certificate_issue_depends_on_open_policy_status
    """
    env = _suspend_the_cover_holding_a_pending_draft(api)

    suspended = read_policy(api, env["policy_id"])
    refused = api.issue_certificate(
        env["pending_draft_id"],
        {"expected_open_policy_version": suspended["version"]},
        UNDERWRITER)
    validate_error(refused, ERR_POLICY_NOT_ACTIVE)

    corrected = submit_declaration(api, env["declaration_id"], env["policy_id"],
                                   EXPECTED_TOTAL_PREMIUM)
    assert corrected["status"] == "SUBMITTED", (
        f"a re-submission must land in SUBMITTED, got {corrected['status']}"
    )
    assert corrected["submission_count"] == 2, (
        f"expected submission_count 2, got {corrected['submission_count']}"
    )

    restored = read_policy(api, env["policy_id"])
    assert restored["status"] == "ACTIVE", (
        f"an accurate report must restore ACTIVE, got {restored['status']}"
    )

    issued = get_success_data(api.issue_certificate(
        env["pending_draft_id"],
        {"expected_open_policy_version": restored["version"]},
        UNDERWRITER))
    assert issued["status"] == "ISSUED", (
        f"expected the freed draft to reach ISSUED, got {issued['status']}"
    )
    assert_money(issued["insured_value"], PENDING_DRAFT_DECLARED_VALUE,
                 "certificate.insured_value")

    policy = read_policy(api, env["policy_id"])
    assert_money(policy["aggregate_insured_value_booked"],
                 EXPECTED_BOOKED_AFTER_BOTH_CERTIFICATES,
                 "policy.aggregate_insured_value_booked")


# ---------------------------------------------------------------------------
# The general average claim that waits for the average to be stated
# ---------------------------------------------------------------------------
# The average act was declared on 2026-08-18, inside the cover interval of the
# certificate the loss is claimed against.
GA_LOSS_DATE = "2026-08-18T00:00:00Z"
GA_DAMAGE_PERCENTAGE = 12.5


def _general_average_claim_adjusted(api: ApiClient) -> JsonDict:
    """
    Two contributors on one conveyance, an average act whose security has been
    called but not yet lodged, and a general average claim on the larger
    contributor taken through adjustment to 141875.00 by the first adjuster.
    """
    env = build_ga_event_with_security_calls(api)
    env["claim"] = open_claim_file(
        api, env["certificate_a_id"],
        loss_type="GENERAL_AVERAGE",
        peril="JETTISON",
        loss_date=GA_LOSS_DATE,
        ga_event_id=env["ga_event_id"],
        damage_percentage=GA_DAMAGE_PERCENTAGE)
    env["claim_id"] = env["claim"]["id"]
    complete_claim_documents(api, env["claim_id"])
    env["claim"] = adjust_claim_file(api, env["claim_id"])
    return env


def _lodge_all_security_and_state_the_average(api: ApiClient,
                                              env: JsonDict) -> JsonDict:
    """Post both called securities in full and close the adjustment."""
    post_ga_security(api, env["posting_a_id"], env["policy_id"],
                     EXPECTED_GA_CONTRIBUTION_LARGEST,
                     EXPECTED_GA_DEPOSIT_LARGEST,
                     ga_event_id=env["ga_event_id"])
    post_ga_security(api, env["posting_d_id"], env["policy_id"],
                     EXPECTED_GA_CONTRIBUTION_SMALLER,
                     EXPECTED_GA_DEPOSIT_SMALLER,
                     ga_event_id=env["ga_event_id"])
    return get_success_data(
        api.finalize_ga_adjustment(env["ga_event_id"], CLAIMS_ADJUSTER))


def test_general_average_claim_cannot_settle_while_security_is_still_collecting(
        api: ApiClient) -> None:
    """
    An adjusted general average claim is refused settlement while the average
    event it is tied to has not itself been stated.

    Where the claim's `loss_type` is `GENERAL_AVERAGE`, settlement additionally waits on the average adjustment: the linked general average event must have reached `ADJUSTED`, failing which the request is refused with `ERR_GA_ADJUSTMENT_PENDING` (HTTP 409).

    Design: Difficulty/cross_entity_state_dependency/claim_settlement_depends_on_general_average_event_status
    """
    env = _general_average_claim_adjusted(api)

    event = read_ga_event(api, env["ga_event_id"], CLAIMS_ADJUSTER)
    assert event["status"] == "SECURITY_COLLECTING", (
        f"expected the event to be SECURITY_COLLECTING, got {event['status']}"
    )
    assert env["claim"]["status"] == "ADJUSTED", (
        f"expected the claim to be ADJUSTED, got {env['claim']['status']}"
    )
    assert_money(env["claim"]["adjusted_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION,
                 "claim.adjusted_amount")

    refused = api.settle_claim_file(env["claim_id"], CLAIMS_ADJUSTER_2)
    validate_error(refused, ERR_GA_ADJUSTMENT_PENDING)

    unmoved = read_claim_file(api, env["claim_id"], CLAIMS_ADJUSTER)
    assert unmoved["status"] == "ADJUSTED", (
        f"the refused settle must leave the claim ADJUSTED, got {unmoved['status']}"
    )
    assert_money(unmoved["adjusted_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION,
                 "claim.adjusted_amount after the refusal")


def test_general_average_claim_settles_once_the_average_has_been_stated(
        api: ApiClient) -> None:
    """
    The identical settle call succeeds and pays 141875.00 once both securities
    are lodged and the average event reaches its terminal state.

    On success the claim reaches the terminal `SETTLED`, `settled_amount` is set to `adjusted_amount`, `net_loss_amount` is set to the adjusted amount minus whatever has been recovered so far, and `settled_by_user_id` records the settling adjuster.

    Design: Difficulty/cross_entity_state_dependency/claim_settlement_depends_on_general_average_event_status
    """
    env = _general_average_claim_adjusted(api)

    refused = api.settle_claim_file(env["claim_id"], CLAIMS_ADJUSTER_2)
    validate_error(refused, ERR_GA_ADJUSTMENT_PENDING)

    stated = _lodge_all_security_and_state_the_average(api, env)
    assert stated["status"] == "ADJUSTED", (
        f"expected the stated average to be ADJUSTED, got {stated['status']}"
    )

    settled = get_success_data(
        api.settle_claim_file(env["claim_id"], CLAIMS_ADJUSTER_2))
    assert settled["status"] == "SETTLED", (
        f"expected the claim to reach SETTLED, got {settled['status']}"
    )
    assert_money(settled["settled_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION, "claim.settled_amount")
    assert_money(settled["net_loss_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION, "claim.net_loss_amount")
    assert settled["adjusted_by_user_id"] == ADJUSTER_USER_ID, (
        f"expected adjusted_by_user_id {ADJUSTER_USER_ID}, "
        f"got {settled['adjusted_by_user_id']}"
    )
    assert settled["settled_by_user_id"] == ADJUSTER_2_USER_ID, (
        f"expected settled_by_user_id {ADJUSTER_2_USER_ID}, "
        f"got {settled['settled_by_user_id']}"
    )


# ---------------------------------------------------------------------------
# The surveyor's closed calendar, inflated by travel time
# ---------------------------------------------------------------------------
# The standing attendance and the two candidate windows around its buffered end.
STANDING_WINDOW_START = "2026-09-08T09:00:00Z"
STANDING_WINDOW_END = "2026-09-08T11:00:00Z"
# 11:00 plus the 45 travel minutes: the inflated end, which still conflicts.
BUFFERED_END_INSTANT = "2026-09-08T11:45:00Z"
BUFFERED_END_WINDOW_END = "2026-09-08T13:45:00Z"
# One minute past the inflated end, which is accepted.
CLEAR_OF_BUFFER_INSTANT = "2026-09-08T11:46:00Z"
CLEAR_OF_BUFFER_WINDOW_END = "2026-09-08T13:46:00Z"

TWO_HOUR_WINDOW_MINUTES = 120
TWO_ACCEPTED_WINDOWS_MINUTES = 240

# The second interest on the same conveyance, stated at an agreed 800000.00.
SECOND_INTEREST_DECLARED_VALUE = 800000
SECOND_LOSS_CLAIMED_AMOUNT = 100000.00
SECOND_LOSS_DATE = "2026-08-21T00:00:00Z"


def _second_claim_beside_one_standing_appointment(api: ApiClient,
                                                  env: JsonDict) -> JsonDict:
    """
    Add a second issued interest on the same conveyance with its own open claim,
    then occupy the surveyor's calendar with a two-hour attendance on the first
    claim so a further request has something to collide with.
    """
    env["certificate_d"] = build_issued_certificate(
        api, env, base=CERTIFICATE_DECLARED_SHIPMENT,
        certificate_number="CERT-D",
        declared_value=SECOND_INTEREST_DECLARED_VALUE,
        package_count=80, gross_weight_kg=12000)
    env["claim_2"] = open_claim_file(
        api, env["certificate_d"]["id"],
        claimed_amount=SECOND_LOSS_CLAIMED_AMOUNT,
        loss_date=SECOND_LOSS_DATE,
        damage_percentage=GA_DAMAGE_PERCENTAGE)
    env["claim_2_id"] = env["claim_2"]["id"]
    env["order_1"] = create_survey_order(
        api, env["claim_id"], env["surveyor_id"],
        STANDING_WINDOW_START, STANDING_WINDOW_END)
    env["order_1_id"] = env["order_1"]["id"]
    return env


def _request_attendance(api: ApiClient, env: JsonDict, claim_file_id: str,
                        window_start_at: str, window_end_at: str):
    """Ask for one attendance window on the environment's panel surveyor."""
    return api.create_survey_order({
        "claim_file_id": claim_file_id,
        "surveyor_id": env["surveyor_id"],
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }, CLAIMS_ADJUSTER)


def test_attendance_window_touching_the_buffered_end_is_refused(
        api: ApiClient, surveyor_env: JsonDict) -> None:
    """
    A window starting exactly on the travel-inflated end of a standing
    attendance collides with it even though the raw windows do not intersect.

    With an existing appointment running 2026-09-08T09:00:00Z to 11:00:00Z and a 45-minute buffer, a request starting at 2026-09-08T11:45:00Z conflicts — the inflated end is exactly 11:45 and the comparison includes it — while one starting at 11:46:00Z is accepted.

    Design: Difficulty/resource_temporal_overlap/surveyor_calendar_closed_interval_with_travel_buffer
    """
    env = _second_claim_beside_one_standing_appointment(api, surveyor_env)

    refused = _request_attendance(api, env, env["claim_2_id"],
                                  BUFFERED_END_INSTANT, BUFFERED_END_WINDOW_END)
    validate_error(refused, ERR_SURVEYOR_WINDOW_CONFLICT)

    surveyor = read_surveyor(api, env["surveyor_id"], CLAIMS_ADJUSTER)
    assert surveyor["booked_minutes_total"] == TWO_HOUR_WINDOW_MINUTES, (
        f"a refused request must book nothing: expected "
        f"{TWO_HOUR_WINDOW_MINUTES}, got {surveyor['booked_minutes_total']}"
    )

    untouched = read_claim_file(api, env["claim_2_id"], CLAIMS_ADJUSTER)
    assert untouched["status"] == "OPENED", (
        f"the refused claim must stay OPENED, got {untouched['status']}"
    )
    assert_total_count(
        api.list_survey_orders(CLAIMS_ADJUSTER,
                               {"surveyor_id": env["surveyor_id"]}),
        1, "survey orders on the surveyor")


def test_attendance_window_one_minute_clear_of_the_buffer_is_appointed(
        api: ApiClient, surveyor_env: JsonDict) -> None:
    """
    Moving the same two-hour request one minute later clears the travel buffer,
    and both attendances then stand on the calendar.

    On success the order is created in `status` `APPOINTED`, its `window_minutes` is computed as the whole number of minutes between the two window instants, the surveyor's `booked_minutes_total` rises by that figure, and the claim moves to `SURVEY_ORDERED` — from `OPENED` on a first survey, or from `DOCS_INCOMPLETE` when the file is going round the rework loop for a further survey.

    Design: Difficulty/resource_temporal_overlap/surveyor_calendar_closed_interval_with_travel_buffer
    """
    env = _second_claim_beside_one_standing_appointment(api, surveyor_env)

    refused = _request_attendance(api, env, env["claim_2_id"],
                                  BUFFERED_END_INSTANT, BUFFERED_END_WINDOW_END)
    validate_error(refused, ERR_SURVEYOR_WINDOW_CONFLICT)

    accepted = get_success_data(_request_attendance(
        api, env, env["claim_2_id"],
        CLEAR_OF_BUFFER_INSTANT, CLEAR_OF_BUFFER_WINDOW_END))
    assert accepted["status"] == "APPOINTED", (
        f"expected the accepted order to be APPOINTED, got {accepted['status']}"
    )
    assert accepted["window_minutes"] == TWO_HOUR_WINDOW_MINUTES, (
        f"expected window_minutes {TWO_HOUR_WINDOW_MINUTES}, "
        f"got {accepted['window_minutes']}"
    )

    surveyor = read_surveyor(api, env["surveyor_id"], CLAIMS_ADJUSTER)
    assert surveyor["booked_minutes_total"] == TWO_ACCEPTED_WINDOWS_MINUTES, (
        f"only the accepted windows are booked: expected "
        f"{TWO_ACCEPTED_WINDOWS_MINUTES}, got {surveyor['booked_minutes_total']}"
    )

    for label, claim_id in (("first", env["claim_id"]),
                            ("second", env["claim_2_id"])):
        claim = read_claim_file(api, claim_id, CLAIMS_ADJUSTER)
        assert claim["status"] == "SURVEY_ORDERED", (
            f"the {label} claim must be SURVEY_ORDERED, got {claim['status']}"
        )

    assert_total_count(
        api.list_survey_orders(CLAIMS_ADJUSTER,
                               {"surveyor_id": env["surveyor_id"]}),
        2, "survey orders on the surveyor")


# ---------------------------------------------------------------------------
# The discharge port's half-open storage window
# ---------------------------------------------------------------------------
# The discharge port is limited to exactly one canonical shipment, so any
# accumulation at all over the storage window breaches it.
TIGHT_DISCHARGE_PORT_LIMIT = 1155000
# Every other capacity is opened up so the storage window is what decides.
ROOMY_ACCUMULATION_LIMIT = 8000000

# The first shipment discharges on 2026-09-05 at a port allowing 30 free storage
# days, so its window closes on 2026-10-05.
FIRST_TRANSIT_TERMINATION = "2026-10-05T00:00:00Z"
# The abutting shipment discharges exactly then, and its own window closes 30
# days later on 2026-11-04.
ABUTTING_SAILING_DATE = "2026-09-20T00:00:00Z"
ABUTTING_DISCHARGE_DATE = "2026-10-05T00:00:00Z"
ABUTTING_TRANSIT_TERMINATION = "2026-11-04T00:00:00Z"
# The overlapping shipment discharges one day earlier, inside the first window.
OVERLAPPING_SAILING_DATE = "2026-09-19T00:00:00Z"
OVERLAPPING_DISCHARGE_DATE = "2026-10-04T00:00:00Z"

# Two canonical shipments standing at the port once the abutting one is issued.
EXPECTED_TWO_SHIPMENT_PORT_LEDGER = 2310000.00


def _tight_discharge_port_environment(api: ApiClient) -> JsonDict:
    """
    The canonical book of business with the discharge port limited to a single
    canonical shipment and every other capacity opened right up.
    """
    return build_canonical_environment(
        api,
        loading_port=dict(PORT_SGSIN,
                          port_accumulation_limit_amount=ROOMY_ACCUMULATION_LIMIT),
        discharge_port=dict(PORT_NLRTM,
                            port_accumulation_limit_amount=TIGHT_DISCHARGE_PORT_LIMIT),
        vessel=dict(VESSEL_KITE,
                    vessel_accumulation_limit_amount=ROOMY_ACCUMULATION_LIMIT),
    )


def _discharge_port_entries(api: ApiClient, env: JsonDict):
    """The port's own discharge-scoped ledger rows."""
    return api.list_accumulation_entries(
        UNDERWRITER, {"port_id": env["discharge_port_id"],
                      "scope_type": "DISCHARGE_PORT"})


def test_storage_window_starting_where_another_ends_does_not_accumulate(
        api: ApiClient) -> None:
    """
    A shipment whose storage window opens on the exact instant the standing
    window closes is issued, even though the port has room for only one of them.

    These windows are half-open, so a window that starts at exactly the instant another ends does **not** accumulate with it.

    Design: Difficulty/resource_temporal_overlap/discharge_port_half_open_storage_window_adjacency
    """
    env = _tight_discharge_port_environment(api)
    standing = build_draft_certificate(api, env)
    abutting = build_draft_certificate(
        api, env, certificate_number="CERT-K",
        sailing_date=ABUTTING_SAILING_DATE,
        discharge_date=ABUTTING_DISCHARGE_DATE)

    issued_standing = issue_certificate(api, standing["id"], env["policy_id"])
    assert_instant(issued_standing["transit_termination_at"],
                   FIRST_TRANSIT_TERMINATION, (
        f"expected transit_termination_at {FIRST_TRANSIT_TERMINATION}, "
        f"got {issued_standing['transit_termination_at']}"
    ))

    issued_abutting = issue_certificate(api, abutting["id"], env["policy_id"])
    assert issued_abutting["status"] == "ISSUED", (
        f"the abutting shipment must be issued, got {issued_abutting['status']}"
    )
    assert_instant(issued_abutting["transit_termination_at"],
                   ABUTTING_TRANSIT_TERMINATION, (
        f"expected transit_termination_at {ABUTTING_TRANSIT_TERMINATION}, "
        f"got {issued_abutting['transit_termination_at']}"
    ))

    port = read_port(api, env["discharge_port_id"])
    assert_money(port["accumulated_insured_value"],
                 EXPECTED_TWO_SHIPMENT_PORT_LEDGER,
                 "discharge port.accumulated_insured_value")
    assert_total_count(_discharge_port_entries(api, env), 2,
                       "discharge-port ledger rows")


def test_storage_window_overlapping_by_one_day_breaches_the_port_limit(
        api: ApiClient) -> None:
    """
    Pulling the same shipment's discharge one day earlier makes the two storage
    windows overlap, and the port's aggregate capacity refuses it.

    The sum plus this insured value must not exceed the discharge port's `port_accumulation_limit_amount`; a breach is `ERR_PORT_ACCUMULATION_EXCEEDED` (HTTP 422).

    Design: Difficulty/resource_temporal_overlap/discharge_port_half_open_storage_window_adjacency
    """
    env = _tight_discharge_port_environment(api)
    standing = build_draft_certificate(api, env)
    overlapping = build_draft_certificate(
        api, env, certificate_number="CERT-L",
        sailing_date=OVERLAPPING_SAILING_DATE,
        discharge_date=OVERLAPPING_DISCHARGE_DATE)

    issue_certificate(api, standing["id"], env["policy_id"])

    refused = api.issue_certificate(
        overlapping["id"],
        {"expected_open_policy_version": policy_version(api, env["policy_id"])},
        UNDERWRITER)
    validate_error(refused, ERR_PORT_ACCUMULATION_EXCEEDED)

    unbooked = read_certificate(api, overlapping["id"])
    assert unbooked["status"] == "DRAFT", (
        f"the refused shipment must stay DRAFT, got {unbooked['status']}"
    )

    port = read_port(api, env["discharge_port_id"])
    assert_money(port["accumulated_insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "discharge port.accumulated_insured_value")
    assert_total_count(_discharge_port_entries(api, env), 1,
                       "discharge-port ledger rows")
