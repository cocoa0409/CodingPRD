"""
Refusals on the loss side: accumulation released by delivery, the survey a large
claim cannot be adjusted without, panel eligibility, short general average
security and a subrogation recovery larger than the settlement.

Each scenario drives the refusal and then the neighbouring request that must be
accepted once the missing condition is supplied, checking along the way that the
refused attempt moved no ledger, no status and no version.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CERTIFICATE_DECLARED_SHIPMENT,
    CLAIMS_ADJUSTER,
    CLAIMS_ADJUSTER_2,
    COMPLIANCE_OFFICER,
    ERR_RECOVERY_EXCEEDS_SETTLEMENT,
    ERR_SECURITY_AMOUNT_INSUFFICIENT,
    ERR_SURVEYOR_INACTIVE,
    ERR_SURVEYOR_NOT_CERTIFIED,
    ERR_SURVEY_REQUIRED,
    ERR_VESSEL_ACCUMULATION_EXCEEDED,
    EXPECTED_CLAIM_ADJUSTED_DEPRECIATION,
    EXPECTED_CLAIM_DEDUCTIBLE_APPLIED,
    EXPECTED_CLAIM_GROSS,
    EXPECTED_INSURED_VALUE_CIF,
    PORT_NLRTM,
    PORT_SGSIN,
    UNDERWRITER,
    VESSEL_KITE,
    ApiClient,
    JsonDict,
    adjust_claim_file,
    assert_instant,
    assert_money,
    assert_total_count,
    build_canonical_environment,
    build_draft_certificate,
    build_issued_certificate,
    complete_claim_documents,
    create_survey_order,
    create_surveyor,
    declare_ga_event,
    file_survey_report,
    ga_event_version,
    ga_posting_for_certificate,
    issue_ga_security_calls,
    make_assured_headers,
    open_claim_file,
    policy_version,
    read_certificate,
    read_claim_file,
    read_ga_event,
    read_ga_posting,
    read_policy,
    read_survey_order,
    read_surveyor,
    read_vessel,
    set_clock,
)

# Ports and hulls that cannot be the binding constraint in these scenarios.
WIDE_LIMIT = 8000000


def _environment(api: ApiClient, policy_number: str,
                 vessel_limit: int = WIDE_LIMIT,
                 **overrides: object) -> JsonDict:
    """
    The canonical book of business with the port buckets widened, the hull's own
    bucket set by the caller and the open cover named for the scenario.
    """
    policy_overrides = dict(overrides.pop("policy_overrides", {}) or {})
    policy_overrides.setdefault("policy_number", policy_number)
    return build_canonical_environment(
        api,
        loading_port=dict(PORT_SGSIN, port_accumulation_limit_amount=WIDE_LIMIT),
        discharge_port=dict(PORT_NLRTM, port_accumulation_limit_amount=WIDE_LIMIT),
        vessel=dict(VESSEL_KITE, vessel_accumulation_limit_amount=vessel_limit),
        policy_overrides=policy_overrides,
        **overrides,
    )


# ---------------------------------------------------------------------------
# The single-hull bucket spans every voyage until delivery releases it
# ---------------------------------------------------------------------------
VOYAGE_VALUE = 1600000
FIRST_SAILING = "2026-08-10T00:00:00Z"
FIRST_DISCHARGE = "2026-09-05T00:00:00Z"
SECOND_SAILING = "2026-08-20T00:00:00Z"
SECOND_DISCHARGE = "2026-09-25T00:00:00Z"
DELIVERY_INSTANT = "2026-09-06T00:00:00Z"
PINNED_TERMINATION = "2026-10-05T00:00:00Z"


def _two_voyage_environment(api: ApiClient) -> JsonDict:
    """
    A 3000000.00 hull bucket carrying one issued 1600000.00 voyage, with an
    identical second voyage sitting in `DRAFT` on a later sailing date.
    """
    env = _environment(
        api, "OP-VSL", vessel_limit=3000000,
        commodity_class_overrides={"code": "CC-FULL",
                                   "susceptibility_rating": "S2",
                                   "max_conveyance_share_pct": 1.00},
        policy_overrides={"per_certificate_limit_amount": 2000000,
                          "conveyance_limit_amount": 2000000,
                          "annual_aggregate_limit_amount": 10000000},
    )
    env["second"] = build_draft_certificate(
        api, env, base=CERTIFICATE_DECLARED_SHIPMENT,
        certificate_number="CERT-L2", declared_value=VOYAGE_VALUE,
        package_count=20, gross_weight_kg=30000,
        sailing_date=SECOND_SAILING, discharge_date=SECOND_DISCHARGE,
        war_cover_requested=False, strikes_cover_requested=False)
    env["first"] = build_issued_certificate(
        api, env, base=CERTIFICATE_DECLARED_SHIPMENT,
        certificate_number="CERT-L1", declared_value=VOYAGE_VALUE,
        package_count=20, gross_weight_kg=30000,
        sailing_date=FIRST_SAILING, discharge_date=FIRST_DISCHARGE,
        war_cover_requested=False, strikes_cover_requested=False)
    return env


def _issue_second_voyage(api: ApiClient, env: JsonDict):
    return api.issue_certificate(
        env["second"]["id"],
        {"expected_open_policy_version": policy_version(api, env["policy_id"])},
        UNDERWRITER)


def _confirm_delivery(api: ApiClient, env: JsonDict) -> JsonDict:
    """Move the clock to the delivery day and confirm it as the assured."""
    set_clock(api, DELIVERY_INSTANT)
    return validate_success(api.confirm_delivery(
        env["first"]["id"], make_assured_headers(env["policy_id"]),
        {"delivered_at": DELIVERY_INSTANT}))


def test_a_second_voyage_is_refused_while_the_hull_still_carries_the_first(
        api: ApiClient):
    """1600000.00 in transit plus a further 1600000.00 breaks the hull's
    3000000.00 bucket even though the two sailings are ten days apart.

    The system sums the `amount` of every accumulation ledger row of scope `VESSEL` on this vessel whose `status` is `ACTIVE`, and the sum plus this insured value must not exceed the vessel's `vessel_accumulation_limit_amount`.

    Design: Corner/validations/vessel_accumulation_blocks_a_second_voyage_until_delivery_releases_the_ledger
    """
    env = _two_voyage_environment(api)

    response = _issue_second_voyage(api, env)

    validate_error(response, ERR_VESSEL_ACCUMULATION_EXCEEDED)
    assert read_certificate(api, env["second"]["id"])["status"] == "DRAFT"
    assert_money(read_vessel(api, env["vessel_id"])["accumulated_insured_value"],
                 float(VOYAGE_VALUE), "vessel.accumulated_insured_value")
    assert_money(read_policy(api, env["policy_id"])["aggregate_insured_value_booked"],
                 float(VOYAGE_VALUE), "policy.aggregate_insured_value_booked")


def test_confirming_delivery_releases_every_active_ledger_row(api: ApiClient):
    """Delivery ends the transit and hands the hull and port buckets back.

    The certificate moves to `TRANSIT_ENDED`, its `ACTIVE` accumulation rows become `RELEASED` with `release_reason` `DELIVERY_CONFIRMED`, both ledgers fall, and the certificate's `version` increments.

    Design: Corner/validations/vessel_accumulation_blocks_a_second_voyage_until_delivery_releases_the_ledger
    """
    env = _two_voyage_environment(api)
    version_before = env["first"]["version"]

    delivered = _confirm_delivery(api, env)

    assert delivered["status"] == "TRANSIT_ENDED", (
        f"confirmed delivery must end the transit, got {delivered['status']}"
    )
    assert delivered["version"] == version_before + 1, (
        "the certificate's version must increment on delivery"
    )
    rows = assert_total_count(
        api.list_accumulation_entries(
            UNDERWRITER, {"certificate_id": env["first"]["id"]}),
        3, "ledger rows of the delivered certificate")
    for row in rows:
        assert row["status"] == "RELEASED", (
            f"{row['scope_type']} row must be RELEASED, got {row['status']}"
        )
        assert row["release_reason"] == "DELIVERY_CONFIRMED", (
            f"{row['scope_type']} row must cite the delivery, got "
            f"{row['release_reason']}"
        )
    assert_money(read_vessel(api, env["vessel_id"])["accumulated_insured_value"],
                 0.00, "vessel.accumulated_insured_value")


def test_delivery_pulls_the_termination_instant_back_from_the_storage_deadline(
        api: ApiClient):
    """The window closes on the 2026-09-06 delivery, not on the 2026-10-05
    storage deadline the issue had pinned.

    The optional `delivered_at` instant may be supplied; when it is earlier than the pinned value, `transit_termination_at` is pulled back to it, so the exposure window closes at the real delivery rather than at the theoretical storage deadline.

    Design: Corner/validations/vessel_accumulation_blocks_a_second_voyage_until_delivery_releases_the_ledger
    """
    env = _two_voyage_environment(api)
    assert_instant(env["first"]["transit_termination_at"], PINNED_TERMINATION, (
        "issue pins 30 free storage days after discharge, got "
        f"{env['first']['transit_termination_at']}"
    ))

    delivered = _confirm_delivery(api, env)

    assert_instant(delivered["transit_termination_at"], DELIVERY_INSTANT, (
        "the earlier delivery must pull the termination back, got "
        f"{delivered['transit_termination_at']}"
    ))


def test_the_identical_second_voyage_issues_once_the_hull_is_free(api: ApiClient):
    """The very request the hull's bucket refused succeeds unchanged after
    delivery, and the annual aggregate keeps both voyages.

    The system sums the `amount` of every accumulation ledger row of scope `VESSEL` on this vessel whose `status` is `ACTIVE`, and the sum plus this insured value must not exceed the vessel's `vessel_accumulation_limit_amount`.

    Design: Corner/validations/vessel_accumulation_blocks_a_second_voyage_until_delivery_releases_the_ledger
    """
    env = _two_voyage_environment(api)
    validate_error(_issue_second_voyage(api, env),
                   ERR_VESSEL_ACCUMULATION_EXCEEDED)
    _confirm_delivery(api, env)

    issued = validate_success(_issue_second_voyage(api, env))

    assert issued["status"] == "ISSUED", (
        f"the freed hull must accept the voyage, got {issued['status']}"
    )
    assert_money(read_vessel(api, env["vessel_id"])["accumulated_insured_value"],
                 float(VOYAGE_VALUE), "vessel.accumulated_insured_value")
    active = assert_total_count(
        api.list_accumulation_entries(
            UNDERWRITER, {"vessel_id": env["vessel_id"], "status": "ACTIVE"}),
        1, "active hull ledger rows")
    assert active[0]["certificate_id"] == env["second"]["id"], (
        "the only live hull row must belong to the second voyage"
    )
    assert_money(read_policy(api, env["policy_id"])["aggregate_insured_value_booked"],
                 float(2 * VOYAGE_VALUE),
                 "policy.aggregate_insured_value_booked")


# ---------------------------------------------------------------------------
# The survey a large claim cannot be adjusted without
# ---------------------------------------------------------------------------
SURVEY_THRESHOLD = 100000
SMALL_CLAIM_AMOUNT = 50000.00
SMALL_CLAIM_DAMAGE = 4.00
EXPECTED_SMALL_ADJUSTED = 43700.00
ATTENDANCE_START = "2026-09-08T09:00:00Z"
ATTENDANCE_END = "2026-09-08T11:00:00Z"


def _survey_threshold_environment(api: ApiClient) -> JsonDict:
    """
    Two issued 1155000.00 certificates on a class that demands a survey above
    100000.00, a big documented claim, a small documented claim, and one active
    surveyor competent for the cargo.
    """
    env = _environment(
        api, "OP-SURVEY",
        commodity_class_overrides={"code": "CC-SURVEY",
                                   "survey_required_above_amount": SURVEY_THRESHOLD},
    )
    env["surveyor"] = create_surveyor(
        api, env["loading_port_id"], panel_code="PANEL-SG-01",
        name="Lim Marine Surveys")
    env["surveyor_id"] = env["surveyor"]["id"]
    env["big_certificate"] = build_issued_certificate(
        api, env, certificate_number="CERT-BIGLOSS",
        war_cover_requested=False, strikes_cover_requested=False)
    env["small_certificate"] = build_issued_certificate(
        api, env, certificate_number="CERT-SMALLLOSS",
        war_cover_requested=False, strikes_cover_requested=False)
    env["big_claim"] = open_claim_file(
        api, env["big_certificate"]["id"], claimed_amount=EXPECTED_CLAIM_GROSS,
        damage_percentage=12.5)
    complete_claim_documents(api, env["big_claim"]["id"],
                             reference_prefix="BIG")
    env["small_claim"] = open_claim_file(
        api, env["small_certificate"]["id"], peril="HANDLING",
        claimed_amount=SMALL_CLAIM_AMOUNT,
        damage_percentage=SMALL_CLAIM_DAMAGE)
    complete_claim_documents(api, env["small_claim"]["id"],
                             reference_prefix="SML")
    return env


def _appoint_and_file(api: ApiClient, env: JsonDict) -> JsonDict:
    """Appoint the competent surveyor and let them file their report."""
    order = create_survey_order(api, env["big_claim"]["id"], env["surveyor_id"],
                                ATTENDANCE_START, ATTENDANCE_END)
    set_clock(api, ATTENDANCE_START)
    file_survey_report(api, order["id"], env["surveyor_id"],
                       report_reference="SR-FIELD-1",
                       damage_percentage_found=12.5)
    return order


def test_a_large_claim_is_refused_adjustment_without_a_filed_survey_report(
        api: ApiClient):
    """A fully documented 144375.00 claim is still refused: a desk survey report
    logged by the adjuster is not an independent survey.

    If the `claimed_amount` exceeds the commodity class's `survey_required_above_amount` and no survey order on this claim has reached `REPORT_FILED`, the adjustment is refused outright with `ERR_SURVEY_REQUIRED` (HTTP 422) — a large loss is not adjusted on the adjuster's word alone.

    Design: Corner/validations/large_claim_cannot_be_adjusted_until_a_survey_report_is_filed
    """
    env = _survey_threshold_environment(api)
    before = read_claim_file(api, env["big_claim"]["id"], CLAIMS_ADJUSTER)
    assert before["documentation_complete"] is True, (
        "the evidence log carries all three mandatory documents"
    )

    response = api.adjust_claim_file(env["big_claim"]["id"], CLAIMS_ADJUSTER)

    validate_error(response, ERR_SURVEY_REQUIRED)
    refused = read_claim_file(api, env["big_claim"]["id"], CLAIMS_ADJUSTER)
    assert refused["status"] == "OPENED", (
        f"the refused claim must stay OPENED, got {refused['status']}"
    )
    assert refused["adjusted_amount"] is None, (
        "a refused adjustment must quantify nothing"
    )


def test_a_claim_under_the_class_threshold_adjusts_with_no_survey_at_all(
        api: ApiClient):
    """A 50000.00 claim is below the 100000.00 threshold, so it travels straight
    to ADJUSTED at 46200.00 less the 2500.00 excess.

    If the `claimed_amount` exceeds the commodity class's `survey_required_above_amount` and no survey order on this claim has reached `REPORT_FILED`, the adjustment is refused outright with `ERR_SURVEY_REQUIRED` (HTTP 422) — a large loss is not adjusted on the adjuster's word alone.

    Design: Corner/validations/large_claim_cannot_be_adjusted_until_a_survey_report_is_filed
    """
    env = _survey_threshold_environment(api)

    adjusted = adjust_claim_file(api, env["small_claim"]["id"])

    assert adjusted["status"] == "ADJUSTED", (
        f"a small documented claim adjusts straight through, got "
        f"{adjusted['status']}"
    )
    assert_money(adjusted["adjusted_amount"], EXPECTED_SMALL_ADJUSTED,
                 "small claim adjusted_amount")
    assert_money(adjusted["deductible_applied_amount"],
                 EXPECTED_CLAIM_DEDUCTIBLE_APPLIED,
                 "small claim deductible_applied_amount")
    assert_total_count(
        api.list_survey_orders(CLAIMS_ADJUSTER,
                               {"claim_file_id": env["small_claim"]["id"]}),
        0, "survey orders on the small claim")


def test_a_filed_survey_report_unlocks_the_identical_adjustment(api: ApiClient):
    """Once the appointed surveyor has filed, the same refused call adjusts the
    big claim to 141875.00.

    With an insured value of 1155000.00, a deductible of 2500.00 and a damage percentage of 12.5, the gross loss is 144375.00 and the adjusted amount is 141875.00.

    Design: Corner/validations/large_claim_cannot_be_adjusted_until_a_survey_report_is_filed
    """
    env = _survey_threshold_environment(api)
    validate_error(api.adjust_claim_file(env["big_claim"]["id"], CLAIMS_ADJUSTER),
                   ERR_SURVEY_REQUIRED)
    order = _appoint_and_file(api, env)
    assert read_survey_order(api, order["id"], CLAIMS_ADJUSTER)["status"] == \
        "REPORT_FILED"

    adjusted = adjust_claim_file(api, env["big_claim"]["id"])

    assert adjusted["status"] == "ADJUSTED", (
        f"the surveyed claim must adjust, got {adjusted['status']}"
    )
    assert_money(adjusted["adjusted_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION,
                 "big claim adjusted_amount")
    assert_money(adjusted["deductible_applied_amount"],
                 EXPECTED_CLAIM_DEDUCTIBLE_APPLIED,
                 "big claim deductible_applied_amount")


def test_the_filed_report_joins_the_evidence_log_as_a_surveyor_document(
        api: ApiClient):
    """Filing appends a fourth document, this one originated by the surveyor
    rather than by the adjuster.

    A damage document of type `SURVEY_REPORT` with `origin` `SURVEYOR` is appended to the claim automatically, and `documentation_complete` is re-derived from the enlarged log — which is often the moment a file becomes complete.

    Design: Corner/validations/large_claim_cannot_be_adjusted_until_a_survey_report_is_filed
    """
    env = _survey_threshold_environment(api)
    _appoint_and_file(api, env)

    rows = assert_total_count(
        api.list_claim_documents(env["big_claim"]["id"], CLAIMS_ADJUSTER),
        4, "documents on the surveyed claim")

    surveyor_rows = [row for row in rows if row["origin"] == "SURVEYOR"]
    assert len(surveyor_rows) == 1, (
        f"exactly one document comes from the surveyor, got {len(surveyor_rows)}"
    )
    assert surveyor_rows[0]["doc_type"] == "SURVEY_REPORT", (
        f"the appended document is the survey report, got "
        f"{surveyor_rows[0]['doc_type']}"
    )
    claim = read_claim_file(api, env["big_claim"]["id"], CLAIMS_ADJUSTER)
    assert claim["documentation_complete"] is True


# ---------------------------------------------------------------------------
# Two eligibility gates on the panel, and the order they run in
# ---------------------------------------------------------------------------
WINDOW_MINUTES = 120


def _panel_environment(api: ApiClient) -> JsonDict:
    """
    An S3 cargo with an open claim and four panel members: one active but
    uncertified, one certified but suspended, one that is neither, and one
    competent and in good standing.
    """
    env = _environment(api, "OP-PANEL")
    env["certificate"] = build_issued_certificate(
        api, env, certificate_number="CERT-PANEL",
        war_cover_requested=False, strikes_cover_requested=False)
    env["claim"] = open_claim_file(
        api, env["certificate"]["id"], claimed_amount=EXPECTED_CLAIM_GROSS,
        damage_percentage=12.5)
    env["wrong"] = create_surveyor(
        api, env["loading_port_id"], name="Tan Adjusters",
        panel_code="PANEL-WRONG", certified_commodity_ratings=["S1", "S2"])
    env["suspended"] = create_surveyor(
        api, env["loading_port_id"], name="Ng Marine",
        panel_code="PANEL-SUSP", certified_commodity_ratings=["S3"])
    env["neither"] = create_surveyor(
        api, env["loading_port_id"], name="Goh Survey",
        panel_code="PANEL-BOTH", certified_commodity_ratings=["S1"])
    env["good"] = create_surveyor(
        api, env["loading_port_id"], name="Lim Marine Surveys",
        panel_code="PANEL-GOOD", certified_commodity_ratings=["S3", "S4"])
    for key in ("suspended", "neither"):
        validate_success(api.suspend_surveyor(env[key]["id"], COMPLIANCE_OFFICER))
    return env


def _appoint(api: ApiClient, env: JsonDict, surveyor_key: str):
    """Ask for the same two-hour attendance window on the named panel member."""
    return api.create_survey_order(
        {"claim_file_id": env["claim"]["id"],
         "surveyor_id": env[surveyor_key]["id"],
         "window_start_at": ATTENDANCE_START,
         "window_end_at": ATTENDANCE_END},
        CLAIMS_ADJUSTER)


def _assert_nothing_booked(api: ApiClient, env: JsonDict,
                           surveyor_key: str) -> None:
    surveyor = read_surveyor(api, env[surveyor_key]["id"], COMPLIANCE_OFFICER)
    assert surveyor["booked_minutes_total"] == 0, (
        "a refused appointment must reserve no calendar minutes, got "
        f"{surveyor['booked_minutes_total']}"
    )
    claim = read_claim_file(api, env["claim"]["id"], CLAIMS_ADJUSTER)
    assert claim["status"] == "OPENED", (
        f"the claim must stay OPENED after a refusal, got {claim['status']}"
    )
    assert_total_count(
        api.list_survey_orders(CLAIMS_ADJUSTER,
                               {"claim_file_id": env["claim"]["id"]}),
        0, "survey orders after a refused appointment")


def test_an_active_surveyor_without_the_cargo_rating_is_refused(api: ApiClient):
    """A surveyor certified for S1 and S2 may not be sent to an S3 loss.

    Next, competence: the surveyor's `certified_commodity_ratings` must contain the `susceptibility_rating` of the commodity class on the claimed certificate, failing which the appointment is refused with `ERR_SURVEYOR_NOT_CERTIFIED` (HTTP 422).

    Design: Corner/validations/survey_appointment_refuses_uncertified_and_suspended_panel_members
    """
    env = _panel_environment(api)

    response = _appoint(api, env, "wrong")

    validate_error(response, ERR_SURVEYOR_NOT_CERTIFIED)
    _assert_nothing_booked(api, env, "wrong")


def test_a_certified_but_suspended_surveyor_is_refused(api: ApiClient):
    """Competence for S3 does not survive suspension from the panel.

    A `ComplianceOfficer` may suspend a surveyor, moving `status` `ACTIVE → SUSPENDED`; existing appointments stand and are still occupying the calendar, but no new order may name a suspended surveyor and no report may be filed by one.

    Design: Corner/validations/survey_appointment_refuses_uncertified_and_suspended_panel_members
    """
    env = _panel_environment(api)
    assert read_surveyor(api, env["suspended"]["id"],
                         COMPLIANCE_OFFICER)["status"] == "SUSPENDED"

    response = _appoint(api, env, "suspended")

    validate_error(response, ERR_SURVEYOR_INACTIVE)
    _assert_nothing_booked(api, env, "suspended")


def test_a_doubly_disqualified_surveyor_reports_the_certification_failure(
        api: ApiClient):
    """Uncertified and suspended at once, the panel member is refused on
    competence — the check that runs first.

    Appointment requires the claim to be `OPENED` or `DOCS_INCOMPLETE`, and then three checks run in this order: the calendar conflict, then the surveyor's certification, then the surveyor's panel standing.

    Design: Corner/validations/survey_appointment_refuses_uncertified_and_suspended_panel_members
    """
    env = _panel_environment(api)
    disqualified = read_surveyor(api, env["neither"]["id"], COMPLIANCE_OFFICER)
    assert disqualified["status"] == "SUSPENDED"
    assert "S3" not in disqualified["certified_commodity_ratings"]

    response = _appoint(api, env, "neither")

    validate_error(response, ERR_SURVEYOR_NOT_CERTIFIED)
    _assert_nothing_booked(api, env, "neither")


def test_the_competent_active_surveyor_books_the_calendar(api: ApiClient):
    """The fourth attempt is the one that reserves two hours and moves the file.

    On success the order is created in `status` `APPOINTED`, its `window_minutes` is computed as the whole number of minutes between the two window instants, the surveyor's `booked_minutes_total` rises by that figure, and the claim moves to `SURVEY_ORDERED` — from `OPENED` on a first survey, or from `DOCS_INCOMPLETE` when the file is going round the rework loop for a further survey.

    Design: Corner/validations/survey_appointment_refuses_uncertified_and_suspended_panel_members
    """
    env = _panel_environment(api)
    validate_error(_appoint(api, env, "wrong"), ERR_SURVEYOR_NOT_CERTIFIED)
    validate_error(_appoint(api, env, "suspended"), ERR_SURVEYOR_INACTIVE)
    validate_error(_appoint(api, env, "neither"), ERR_SURVEYOR_NOT_CERTIFIED)

    order = validate_success(_appoint(api, env, "good"), 201)

    assert order["status"] == "APPOINTED", (
        f"the competent surveyor must be appointed, got {order['status']}"
    )
    assert order["window_minutes"] == WINDOW_MINUTES, (
        f"09:00 to 11:00 is 120 minutes, got {order['window_minutes']}"
    )
    good = read_surveyor(api, env["good"]["id"], COMPLIANCE_OFFICER)
    assert good["booked_minutes_total"] == WINDOW_MINUTES, (
        f"the appointment books 120 minutes, got {good['booked_minutes_total']}"
    )
    wrong = read_surveyor(api, env["wrong"]["id"], COMPLIANCE_OFFICER)
    assert wrong["booked_minutes_total"] == 0, (
        "the three refusals reserved nothing"
    )
    claim = read_claim_file(api, env["claim"]["id"], CLAIMS_ADJUSTER)
    assert claim["status"] == "SURVEY_ORDERED", (
        f"the claim must move to SURVEY_ORDERED, got {claim['status']}"
    )
    assert_total_count(
        api.list_survey_orders(CLAIMS_ADJUSTER,
                               {"claim_file_id": env["claim"]["id"]}),
        1, "survey orders on the claim")


# ---------------------------------------------------------------------------
# General average security: two amounts, two different computed figures
# ---------------------------------------------------------------------------
# One contributor of 1155000.00 carries the whole 157500.00 allowance, and a
# fifth of that contribution is wanted in cash.
SOLE_CONTRIBUTION = 157500.00
SOLE_DEPOSIT = 31500.00


def _single_contributor_average(api: ApiClient) -> JsonDict:
    """
    One issued 1155000.00 certificate, a declared average of 120000.00 sacrifice
    and 30000.00 salvage, and its single security call outstanding.
    """
    env = _environment(api, "OP-GASEC")
    env["certificate"] = build_issued_certificate(
        api, env, certificate_number="CERT-GASEC",
        war_cover_requested=False, strikes_cover_requested=False)
    event = declare_ga_event(api, env["vessel_id"])
    env["ga_event_id"] = event["id"]
    issue_ga_security_calls(api, event["id"])
    env["posting"] = ga_posting_for_certificate(
        api, event["id"], env["certificate"]["id"])
    env["posting_id"] = env["posting"]["id"]
    env["called_version"] = ga_event_version(api, event["id"])
    return env


def _post_security(api: ApiClient, env: JsonDict, guarantee_amount: float,
                   cash_deposit_amount: float):
    """Lodge security as the assured, always against the version first called."""
    return api.post_ga_security(
        env["posting_id"],
        {"expected_ga_event_version": env["called_version"],
         "guarantee_amount": guarantee_amount,
         "cash_deposit_amount": cash_deposit_amount},
        make_assured_headers(env["policy_id"]))


def _assert_nothing_lodged(api: ApiClient, env: JsonDict) -> None:
    posting = read_ga_posting(api, env["posting_id"], CLAIMS_ADJUSTER)
    assert posting["status"] == "REQUIRED", (
        f"a refused posting stays REQUIRED, got {posting['status']}"
    )
    assert_money(read_policy(api, env["policy_id"])["security_deposit_held_amount"],
                 0.00, "policy.security_deposit_held_amount")
    event = read_ga_event(api, env["ga_event_id"], CLAIMS_ADJUSTER)
    assert event["version"] == env["called_version"], (
        "a refused posting must not consume the event's version"
    )
    assert event["postings_posted_count"] == 0


def test_the_called_deposit_is_a_fifth_of_the_called_contribution(
        api: ApiClient):
    """157500.00 clears the 25000 cash trigger, so 31500.00 is wanted in cash
    alongside the guarantee.

    Whether cash is wanted as well as a guarantee is then decided per posting: `cash_deposit_required` is true when the contribution amount exceeds 25000, and where it is true, `cash_deposit_expected_amount` is twenty percent of the contribution amount rounded half up to 2 decimals, while a posting that needs no cash carries an expected deposit of 0.00.

    Design: Corner/validations/security_posting_rejects_a_short_guarantee_or_a_short_cash_deposit
    """
    env = _single_contributor_average(api)

    posting = read_ga_posting(api, env["posting_id"], CLAIMS_ADJUSTER)

    assert_money(posting["contributory_value"], EXPECTED_INSURED_VALUE_CIF,
                 "posting.contributory_value")
    assert_money(posting["contribution_amount"], SOLE_CONTRIBUTION,
                 "posting.contribution_amount")
    assert posting["cash_deposit_required"] is True, (
        "a contribution above 25000 must call for cash as well"
    )
    assert_money(posting["cash_deposit_expected_amount"], SOLE_DEPOSIT,
                 "posting.cash_deposit_expected_amount")


def test_a_guarantee_one_cent_short_refuses_the_whole_posting(api: ApiClient):
    """157499.99 against a called 157500.00 refuses the posting even though the
    cash leg is exact.

    Both amounts are then tested: the guarantee must be at least the called `contribution_amount` and the cash deposit must be at least `cash_deposit_expected_amount`; either shortfall is refused with `ERR_SECURITY_AMOUNT_INSUFFICIENT` (HTTP 422).

    Design: Corner/validations/security_posting_rejects_a_short_guarantee_or_a_short_cash_deposit
    """
    env = _single_contributor_average(api)

    response = _post_security(api, env, 157499.99, SOLE_DEPOSIT)

    validate_error(response, ERR_SECURITY_AMOUNT_INSUFFICIENT)
    _assert_nothing_lodged(api, env)


def test_a_cash_deposit_one_cent_short_refuses_the_whole_posting(api: ApiClient):
    """31499.99 against a called 31500.00 refuses the posting even though the
    guarantee is exact.

    Both amounts are then tested: the guarantee must be at least the called `contribution_amount` and the cash deposit must be at least `cash_deposit_expected_amount`; either shortfall is refused with `ERR_SECURITY_AMOUNT_INSUFFICIENT` (HTTP 422).

    Design: Corner/validations/security_posting_rejects_a_short_guarantee_or_a_short_cash_deposit
    """
    env = _single_contributor_average(api)

    response = _post_security(api, env, SOLE_CONTRIBUTION, 31499.99)

    validate_error(response, ERR_SECURITY_AMOUNT_INSUFFICIENT)
    _assert_nothing_lodged(api, env)


def test_the_exact_pair_lodges_the_security_and_moves_the_deposit_ledger(
        api: ApiClient):
    """The third attempt, on the same event version the two refusals left
    untouched, posts 157500.00 and 31500.00.

    On success the posting moves `REQUIRED → POSTED` with both amounts stored, the certificate's own policy has its `security_deposit_held_amount` increased by the cash deposit, and the event's `postings_posted_count` increments and its `version` increments.

    Design: Corner/validations/security_posting_rejects_a_short_guarantee_or_a_short_cash_deposit
    """
    env = _single_contributor_average(api)
    validate_error(_post_security(api, env, 157499.99, SOLE_DEPOSIT),
                   ERR_SECURITY_AMOUNT_INSUFFICIENT)
    validate_error(_post_security(api, env, SOLE_CONTRIBUTION, 31499.99),
                   ERR_SECURITY_AMOUNT_INSUFFICIENT)

    posted = validate_success(
        _post_security(api, env, SOLE_CONTRIBUTION, SOLE_DEPOSIT))

    assert posted["status"] == "POSTED", (
        f"the exact pair must be accepted, got {posted['status']}"
    )
    assert_money(posted["guarantee_amount"], SOLE_CONTRIBUTION,
                 "posting.guarantee_amount")
    assert_money(posted["cash_deposit_amount"], SOLE_DEPOSIT,
                 "posting.cash_deposit_amount")
    assert_money(read_policy(api, env["policy_id"])["security_deposit_held_amount"],
                 SOLE_DEPOSIT, "policy.security_deposit_held_amount")
    event = read_ga_event(api, env["ga_event_id"], CLAIMS_ADJUSTER)
    assert event["postings_posted_count"] == 1
    assert event["version"] == env["called_version"] + 1, (
        "only the accepted posting consumes the event's version"
    )


def test_the_last_posting_completes_the_security_collection(api: ApiClient):
    """With the only call satisfied, the average has all the security it asked
    for and says so in the same request.

    When that counter reaches `postings_required_count` as a consequence of the posting just accepted, the event moves `SECURITY_COLLECTING → SECURITY_COMPLETE` in the same request.

    Design: Corner/validations/security_posting_rejects_a_short_guarantee_or_a_short_cash_deposit
    """
    env = _single_contributor_average(api)

    validate_success(_post_security(api, env, SOLE_CONTRIBUTION, SOLE_DEPOSIT))

    event = read_ga_event(api, env["ga_event_id"], CLAIMS_ADJUSTER)
    assert event["status"] == "SECURITY_COMPLETE", (
        f"the event must complete its collection, got {event['status']}"
    )
    assert event["postings_posted_count"] == event["postings_required_count"] == 1


# ---------------------------------------------------------------------------
# Subrogation may not return more than the insurer paid out
# ---------------------------------------------------------------------------
CARRIER_NAME = "Kite Lines Ltd"
NOTICE_INSTANT = "2026-08-01T00:00:00Z"
TIME_BAR_INSTANT = "2027-09-05T00:00:00Z"


def _settled_claim(api: ApiClient) -> JsonDict:
    """
    A documented 144375.00 claim adjusted to 141875.00 by one adjuster and
    settled by another, as segregation of duties requires.
    """
    env = _environment(api, "OP-SUBRO")
    env["certificate"] = build_issued_certificate(
        api, env, certificate_number="CERT-SUBRO",
        war_cover_requested=False, strikes_cover_requested=False)
    env["claim"] = open_claim_file(
        api, env["certificate"]["id"], peril="THEFT",
        claimed_amount=EXPECTED_CLAIM_GROSS, damage_percentage=12.5)
    complete_claim_documents(api, env["claim"]["id"],
                             reference_prefix="SUBRO")
    env["adjusted"] = adjust_claim_file(api, env["claim"]["id"])
    env["settled"] = validate_success(
        api.settle_claim_file(env["claim"]["id"], CLAIMS_ADJUSTER_2))
    return env


def _claim_with_notice(api: ApiClient) -> JsonDict:
    """The same settled claim with notice already served on the carrier."""
    env = _settled_claim(api)
    env["notice"] = validate_success(api.send_subrogation_notice(
        env["claim"]["id"], {"carrier_name": CARRIER_NAME}, CLAIMS_ADJUSTER_2))
    return env


def _record_recovery(api: ApiClient, env: JsonDict, recovered_amount: float):
    return api.record_subrogation_recovery(
        env["claim"]["id"], {"recovered_amount": recovered_amount},
        CLAIMS_ADJUSTER_2)


def test_serving_notice_opens_the_recovery_axis_at_the_clock_instant(
        api: ApiClient):
    """Notice on the carrier is served at the logical clock, well inside the
    time bar the adjustment pinned.

    On success the axis moves `NOT_STARTED → NOTICE_SENT`, the carrier name is stored and `subrogation_notice_at` records the clock instant.

    Design: Corner/validations/subrogation_recovery_cannot_exceed_the_settled_amount
    """
    env = _settled_claim(api)

    noticed = validate_success(api.send_subrogation_notice(
        env["claim"]["id"], {"carrier_name": CARRIER_NAME}, CLAIMS_ADJUSTER_2))

    assert noticed["subrogation_status"] == "NOTICE_SENT", (
        f"the axis must open, got {noticed['subrogation_status']}"
    )
    assert noticed["carrier_name"] == CARRIER_NAME
    assert_instant(noticed["subrogation_notice_at"], NOTICE_INSTANT, (
        "the notice records the clock instant, got "
        f"{noticed['subrogation_notice_at']}"
    ))
    assert_instant(noticed["time_bar_at"], TIME_BAR_INSTANT, "time_bar_at")


def test_the_settlement_is_the_adjusted_amount_net_of_the_excess(api: ApiClient):
    """The figure a recovery is capped against is 141875.00 — the adjustment net
    of the 2500.00 excess, not the 144375.00 claimed.

    On success the claim reaches the terminal `SETTLED`, `settled_amount` is set to `adjusted_amount`, `net_loss_amount` is set to the adjusted amount minus whatever has been recovered so far, and `settled_by_user_id` records the settling adjuster.

    Design: Corner/validations/subrogation_recovery_cannot_exceed_the_settled_amount
    """
    env = _settled_claim(api)

    settled = read_claim_file(api, env["claim"]["id"], CLAIMS_ADJUSTER_2)

    assert settled["status"] == "SETTLED", (
        f"the claim must be settled, got {settled['status']}"
    )
    assert_money(settled["claimed_amount"], EXPECTED_CLAIM_GROSS,
                 "claim.claimed_amount")
    assert_money(settled["adjusted_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION, "claim.adjusted_amount")
    assert_money(settled["settled_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION, "claim.settled_amount")
    assert_money(settled["net_loss_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION, "claim.net_loss_amount")
    assert_money(settled["deductible_applied_amount"],
                 EXPECTED_CLAIM_DEDUCTIBLE_APPLIED,
                 "claim.deductible_applied_amount")


def test_a_recovery_one_cent_over_the_settlement_is_refused(api: ApiClient):
    """141875.01 is refused although it is still 2499.99 under the claimed
    144375.00.

    Once notice has been served and the claim has been settled, a recovery can be booked: the adjuster supplies `recovered_amount`, which must not exceed the claim's `settled_amount` — subrogation may not return more than was paid out — on pain of `ERR_RECOVERY_EXCEEDS_SETTLEMENT` (HTTP 422).

    Design: Corner/validations/subrogation_recovery_cannot_exceed_the_settled_amount
    """
    env = _claim_with_notice(api)

    response = _record_recovery(api, env, 141875.01)

    validate_error(response, ERR_RECOVERY_EXCEEDS_SETTLEMENT)
    refused = read_claim_file(api, env["claim"]["id"], CLAIMS_ADJUSTER_2)
    assert refused["subrogation_status"] == "NOTICE_SENT", (
        "a refused recovery leaves the axis where it was, got "
        f"{refused['subrogation_status']}"
    )
    assert_money(refused["recovered_amount"], 0.00, "claim.recovered_amount")
    assert_money(refused["net_loss_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION, "claim.net_loss_amount")


def test_a_recovery_equal_to_the_settlement_closes_the_net_loss(api: ApiClient):
    """The identical call at 141875.00 is accepted and drives the net loss to
    exactly 0.00, while the claim itself stays SETTLED.

    The axis moves to the terminal `RECOVERED`, the amount is stored, and `net_loss_amount` is restated as the settled amount minus the recovered amount.

    Design: Corner/validations/subrogation_recovery_cannot_exceed_the_settled_amount
    """
    env = _claim_with_notice(api)
    validate_error(_record_recovery(api, env, 141875.01),
                   ERR_RECOVERY_EXCEEDS_SETTLEMENT)

    recovered = validate_success(
        _record_recovery(api, env, EXPECTED_CLAIM_ADJUSTED_DEPRECIATION))

    assert recovered["subrogation_status"] == "RECOVERED", (
        f"the axis must reach RECOVERED, got {recovered['subrogation_status']}"
    )
    assert_money(recovered["recovered_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION,
                 "claim.recovered_amount")
    assert_money(recovered["net_loss_amount"], 0.00, "claim.net_loss_amount")
    assert recovered["status"] == "SETTLED", (
        f"the claim's own lifecycle must not move, got {recovered['status']}"
    )
