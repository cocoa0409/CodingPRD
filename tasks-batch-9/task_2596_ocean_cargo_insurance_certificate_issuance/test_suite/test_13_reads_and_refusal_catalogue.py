"""
Ledger and panel reads, the selective transit sweep, and the refusals that
guard delivery confirmation, war cover, general average security calls and
malformed requests.

Every scenario builds its own book of business through the documented
endpoints, then reads it back through the collection filters the API publishes.
"""

from prd_bench_local_runner.testing import (
    assert_version_incremented,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CERTIFICATE_CIF_SHIPMENT,
    CLAIMS_ADJUSTER,
    COMMODITY_CLASS_ELECTRONICS,
    COMPLIANCE_OFFICER,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NO_CONTRIBUTING_CERTIFICATES,
    ERR_WAR_COVER_TERMINATED,
    EXPECTED_BASE_PREMIUM,
    EXPECTED_INSURED_VALUE_CIF,
    EXPECTED_TRANSIT_TERMINATION,
    PORT_NLRTM,
    PORT_SGSIN,
    PORT_USNYC,
    PREMIUM_AUDITOR,
    UNDERWRITER,
    ApiClient,
    JsonDict,
    assert_instant,
    assert_money,
    assert_ratio,
    assert_total_count,
    build_canonical_environment,
    build_draft_certificate,
    collect_ids,
    create_port,
    create_surveyor,
    declare_ga_event,
    find_row,
    issue_certificate,
    make_assured_headers,
    policy_version,
    read_certificate,
    read_policy,
    read_port,
    read_vessel,
    set_clock,
)

# The voyage the canonical shipment sails: cover attaches on the sailing date
# and the goods are discharged twenty-six days later.
SAILING_AT = "2026-08-10T00:00:00Z"
DISCHARGE_AT = "2026-09-05T00:00:00Z"

# A shorter voyage on the same conveyance: discharged 2026-08-20, so with the
# discharge port's thirty free storage days transit terminates 2026-09-19.
EARLY_DISCHARGE_AT = "2026-08-20T00:00:00Z"
EARLY_TRANSIT_TERMINATION = "2026-09-19T00:00:00Z"

# General average over the single 1155000.00 line: sacrifice 120000.00 plus
# salvage 30000.00 plus the 5% adjuster's fee of 7500.00 is an allowance of
# 157500.00 against a contributory value of 1155000.00.
GA_TOTAL_ALLOWANCE_ONE_LINE = 157500.00
GA_RATE_ONE_LINE = 0.136364

# The three mandatory ledger scopes one issue writes.
LEDGER_SCOPES = ["VESSEL", "LOADING_PORT", "DISCHARGE_PORT"]


def _issue_without_war(api: ApiClient, env: JsonDict, **overrides: object) -> JsonDict:
    """Declare and issue one CIF shipment that buys neither war nor strikes."""
    draft = build_draft_certificate(
        api, env,
        war_cover_requested=False,
        strikes_cover_requested=False,
        **overrides,
    )
    return issue_certificate(api, draft["id"], env["policy_id"])


def _build_one_issued_shipment(api: ApiClient) -> JsonDict:
    """
    One active open cover, a screened hull, two green ports and one issued
    certificate insured for 1155000.00 sailing 2026-08-10 for 2026-09-05.
    """
    env = build_canonical_environment(api)
    env["certificate"] = _issue_without_war(
        api, env, certificate_number="CERT-LEDGER")
    env["certificate_id"] = env["certificate"]["id"]
    return env


def _build_two_panels(api: ApiClient) -> JsonDict:
    """
    Two ports with their own panels: Singapore carries an active member and a
    suspended one, Rotterdam carries a single active member. The two later
    surveyors are posted without a travel allowance so the default applies.
    """
    port_sg = create_port(api, PORT_SGSIN)
    port_nl = create_port(api, PORT_NLRTM)
    surveyor_sg_a = create_surveyor(
        api, port_sg["id"], name="Lim Marine Surveys",
        panel_code="PANEL-SG-A", certified_commodity_ratings=["S3", "S4"],
        travel_buffer_minutes=45)
    surveyor_sg_b = get_success_data(api.create_surveyor(
        {"name": "Ng Marine", "panel_code": "PANEL-SG-B",
         "base_port_id": port_sg["id"],
         "certified_commodity_ratings": ["S1", "S2"]},
        COMPLIANCE_OFFICER))
    surveyor_nl_a = get_success_data(api.create_surveyor(
        {"name": "Van Dijk Expertise", "panel_code": "PANEL-NL-A",
         "base_port_id": port_nl["id"],
         "certified_commodity_ratings": ["S3"]},
        COMPLIANCE_OFFICER))
    validate_success(api.suspend_surveyor(surveyor_sg_b["id"], COMPLIANCE_OFFICER))
    return {
        "port_sg_id": port_sg["id"],
        "port_nl_id": port_nl["id"],
        "surveyor_sg_a_id": surveyor_sg_a["id"],
        "surveyor_sg_b_id": surveyor_sg_b["id"],
        "surveyor_nl_a_id": surveyor_nl_a["id"],
    }


def _build_two_transit_windows(api: ApiClient) -> JsonDict:
    """
    One conveyance carrying two issued certificates of 1155000.00 each: one
    discharged 2026-08-20 and one discharged 2026-09-05, so their pinned
    termination instants are thirty free storage days apart.
    """
    env = build_canonical_environment(api)
    env["certificate_early"] = _issue_without_war(
        api, env, certificate_number="CERT-EARLY",
        discharge_date=EARLY_DISCHARGE_AT)
    env["certificate_late"] = _issue_without_war(
        api, env, certificate_number="CERT-LATE", discharge_date=DISCHARGE_AT)
    env["certificate_early_id"] = env["certificate_early"]["id"]
    env["certificate_late_id"] = env["certificate_late"]["id"]
    return env


def _build_war_terminated_book(api: ApiClient) -> JsonDict:
    """
    One issued certificate exposed to Rotterdam, plus two drafts waiting on the
    same cover — one buying war and strikes, one buying neither. Rotterdam is
    then listed, which terminates the cover's war axis.
    """
    env = build_canonical_environment(api)
    draft_w1 = build_draft_certificate(api, env, certificate_number="CERT-W1")
    env["certificate_w1"] = issue_certificate(
        api, draft_w1["id"], env["policy_id"])
    env["draft_w2"] = build_draft_certificate(
        api, env, certificate_number="CERT-W2",
        sailing_date="2026-08-11T00:00:00Z",
        discharge_date="2026-09-06T00:00:00Z")
    env["draft_w3"] = build_draft_certificate(
        api, env, certificate_number="CERT-W3",
        sailing_date="2026-08-12T00:00:00Z",
        discharge_date="2026-09-07T00:00:00Z",
        war_cover_requested=False, strikes_cover_requested=False)
    validate_success(api.set_port_war_risk_tier(
        env["discharge_port_id"], {"war_risk_tier": "LISTED_AREA"},
        COMPLIANCE_OFFICER))
    policy = read_policy(api, env["policy_id"])
    assert policy["war_cover_status"] == "TERMINATED", (
        "the listing cascade must have terminated the cover's war axis"
    )
    assert policy["war_termination_port_unlocode"] == PORT_NLRTM["unlocode"]
    env["policy"] = policy
    return env


def _build_ga_voyages(api: ApiClient) -> JsonDict:
    """
    One hull with an issued line on the 2026-08-10 voyage and a draft line on
    the 2026-08-25 voyage, and a general average declared over each voyage.
    """
    env = build_canonical_environment(api)
    env["certificate_v1"] = _issue_without_war(
        api, env, certificate_number="CERT-V1")
    env["certificate_v2"] = build_draft_certificate(
        api, env, certificate_number="CERT-V2",
        sailing_date="2026-08-25T00:00:00Z",
        discharge_date="2026-09-20T00:00:00Z",
        war_cover_requested=False, strikes_cover_requested=False)
    env["event_wrong"] = declare_ga_event(
        api, env["vessel_id"], voyage_sailing_date="2026-08-25T00:00:00Z",
        declaration_date="2026-08-28T00:00:00Z")
    env["event_right"] = declare_ga_event(
        api, env["vessel_id"], voyage_sailing_date=SAILING_AT,
        declaration_date="2026-08-22T00:00:00Z")
    return env


def test_issue_writes_one_active_ledger_row_per_scope_at_the_insured_value(
        api: ApiClient) -> None:
    """
    One issue call writes exactly three ACTIVE ledger rows — vessel, loading
    port and discharge port — each carrying the insured value, not the premium.

    Three accumulation ledger rows are created in `status` `ACTIVE`, each with `amount` equal to the certificate's insured value at this instant and `release_reason` `NONE`: one of `scope_type` `VESSEL` carrying `vessel_id`, one of `scope_type` `LOADING_PORT` carrying the loading `port_id`, and one of `scope_type` `DISCHARGE_PORT` carrying the discharge `port_id`.

    Design: Corner/endpoints/accumulation_ledger_rows_expose_three_scopes_with_distinct_exposure_windows
    """
    env = _build_one_issued_shipment(api)
    certificate_id = env["certificate_id"]

    rows, meta = validate_paginated(api.list_accumulation_entries(
        UNDERWRITER, {"certificate_id": certificate_id}))
    assert meta["total_count"] == 3, (
        f"one issue must write three ledger rows, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "three rows fit inside the default page"
    assert len(rows) == 3

    assert sorted(row["scope_type"] for row in rows) == sorted(LEDGER_SCOPES)
    for row in rows:
        assert row["certificate_id"] == certificate_id
        assert row["status"] == "ACTIVE", (
            f"{row['scope_type']} row must be ACTIVE while the certificate is ISSUED"
        )
        assert row["release_reason"] == "NONE"
        assert_money(row["amount"], EXPECTED_INSURED_VALUE_CIF,
                     f"{row['scope_type']} ledger amount")

    assert_total_count(
        api.list_accumulation_entries(
            UNDERWRITER, {"certificate_id": certificate_id, "status": "RELEASED"}),
        0, "released rows on an issued certificate")


def test_ledger_windows_differ_between_the_conveyance_leg_and_the_storage_leg(
        api: ApiClient) -> None:
    """
    The vessel and loading-port rows occupy attachment to discharge while the
    discharge-port row occupies discharge to the transit-termination instant.

    The vessel-scoped and loading-port-scoped rows occupy the interval from the attachment instant as `window_start_at` to the discharge instant as `window_end_at`; the discharge-port row occupies the interval from the discharge instant as `window_start_at` to the transit-termination instant as `window_end_at`.

    Design: Corner/endpoints/accumulation_ledger_rows_expose_three_scopes_with_distinct_exposure_windows
    """
    env = _build_one_issued_shipment(api)
    certificate_id = env["certificate_id"]

    discharge_rows = assert_total_count(
        api.list_accumulation_entries(
            UNDERWRITER,
            {"certificate_id": certificate_id, "scope_type": "DISCHARGE_PORT"}),
        1, "discharge-port ledger rows")
    discharge_row = discharge_rows[0]
    assert_instant(discharge_row["window_start_at"], DISCHARGE_AT,
                   "discharge-port row.window_start_at")
    assert_instant(discharge_row["window_end_at"], EXPECTED_TRANSIT_TERMINATION,
                   "discharge-port row.window_end_at")
    assert discharge_row["port_id"] == env["discharge_port_id"]

    single = validate_success(
        api.get_accumulation_entry(discharge_row["id"], PREMIUM_AUDITOR))
    assert single["id"] == discharge_row["id"]
    assert_instant(single["window_start_at"], DISCHARGE_AT,
                   "single row.window_start_at")
    assert_instant(single["window_end_at"], EXPECTED_TRANSIT_TERMINATION,
                   "single row.window_end_at")
    assert_money(single["amount"], EXPECTED_INSURED_VALUE_CIF,
                 "discharge-port ledger amount")

    vessel_rows = assert_total_count(
        api.list_accumulation_entries(
            UNDERWRITER, {"vessel_id": env["vessel_id"], "scope_type": "VESSEL"}),
        1, "vessel ledger rows")
    assert_instant(vessel_rows[0]["window_start_at"], SAILING_AT,
                   "vessel row.window_start_at")
    assert_instant(vessel_rows[0]["window_end_at"], DISCHARGE_AT,
                   "vessel row.window_end_at")
    assert vessel_rows[0]["vessel_id"] == env["vessel_id"]

    loading_rows = assert_total_count(
        api.list_accumulation_entries(
            COMPLIANCE_OFFICER, {"port_id": env["loading_port_id"]}),
        1, "loading-port ledger rows")
    assert loading_rows[0]["scope_type"] == "LOADING_PORT"
    assert_instant(loading_rows[0]["window_start_at"], SAILING_AT,
                   "loading-port row.window_start_at")
    assert_instant(loading_rows[0]["window_end_at"], DISCHARGE_AT,
                   "loading-port row.window_end_at")


def test_port_panel_lists_only_the_surveyors_based_at_that_port(
        api: ApiClient) -> None:
    """
    A surveyor appears on the panel of the port named by its `base_port_id` and
    on no other port's panel.

    A `ComplianceOfficer` appoints a surveyor with a `name`, a `panel_code` unique across the panel, and a `base_port_id` naming the port they are based at.

    Design: Corner/endpoints/port_surveyor_panel_returns_only_that_ports_members
    """
    panels = _build_two_panels(api)

    singapore = assert_total_count(
        api.list_port_surveyors(panels["port_sg_id"], CLAIMS_ADJUSTER),
        2, "Singapore panel")
    assert sorted(collect_ids(singapore)) == sorted(
        [panels["surveyor_sg_a_id"], panels["surveyor_sg_b_id"]])
    for row in singapore:
        assert row["base_port_id"] == panels["port_sg_id"]

    rotterdam = assert_total_count(
        api.list_port_surveyors(panels["port_nl_id"], UNDERWRITER),
        1, "Rotterdam panel")
    assert collect_ids(rotterdam) == [panels["surveyor_nl_a_id"]]
    assert panels["surveyor_sg_a_id"] not in collect_ids(rotterdam), (
        "a Singapore member must never appear on the Rotterdam panel"
    )
    for row in rotterdam:
        assert row["base_port_id"] == panels["port_nl_id"]


def test_port_panel_status_filter_hides_a_suspended_member(
        api: ApiClient) -> None:
    """
    Narrowing the panel by `status` returns the active member alone, while the
    unfiltered panel still carries the suspended one.

    A port's panel can be read back as a list of surveyors, optionally narrowed by `status`; a surveyor read individually exposes `booked_minutes_total` so an adjuster can see the load before appointing.

    Design: Corner/endpoints/port_surveyor_panel_returns_only_that_ports_members
    """
    panels = _build_two_panels(api)

    active = assert_total_count(
        api.list_port_surveyors(panels["port_sg_id"], CLAIMS_ADJUSTER,
                                {"status": "ACTIVE"}),
        1, "active Singapore panel")
    assert collect_ids(active) == [panels["surveyor_sg_a_id"]]
    assert active[0]["status"] == "ACTIVE"

    unfiltered = assert_total_count(
        api.list_port_surveyors(panels["port_sg_id"], COMPLIANCE_OFFICER),
        2, "unfiltered Singapore panel")
    suspended = find_row(unfiltered, id=panels["surveyor_sg_b_id"])
    assert suspended["status"] == "SUSPENDED", (
        "the suspended member stays on the panel, it is only hidden by the filter"
    )
    assert suspended["booked_minutes_total"] == 0


def test_panel_pagination_reports_the_panel_size_rather_than_the_page_size(
        api: ApiClient) -> None:
    """
    A one-row page over a two-member panel still reports a total of two and
    signals that rows remain.

    `total_count` is the number of rows matching the filter before pagination is applied, and `has_more` is true when rows remain beyond the returned page.

    Design: Corner/endpoints/port_surveyor_panel_returns_only_that_ports_members
    """
    panels = _build_two_panels(api)

    rows, meta = validate_paginated(api.list_port_surveyors(
        panels["port_sg_id"], COMPLIANCE_OFFICER, {"limit": 1, "offset": 0}))
    assert len(rows) == 1, "limit=1 must return a single row"
    assert meta["total_count"] == 2, (
        f"total_count counts the panel, got {meta['total_count']}"
    )
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0

    second_page, second_meta = validate_paginated(api.list_port_surveyors(
        panels["port_sg_id"], COMPLIANCE_OFFICER, {"limit": 1, "offset": 1}))
    assert len(second_page) == 1
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False, (
        "the second row of two exhausts the panel"
    )
    assert collect_ids(second_page) != collect_ids(rows), (
        "the two pages must partition the panel rather than repeat a member"
    )
    assert set(collect_ids(rows) + collect_ids(second_page)) == {
        panels["surveyor_sg_a_id"], panels["surveyor_sg_b_id"]}


def test_sweep_ends_only_the_certificate_whose_termination_instant_has_passed(
        api: ApiClient) -> None:
    """
    With the clock at 2026-09-20 the sweep ends the certificate that terminated
    on 2026-09-19 and leaves the one terminating on 2026-10-05 running.

    Every certificate of the policy in `status` `ISSUED` whose `transit_termination_at` the clock has reached or passed moves `ISSUED → TRANSIT_ENDED`; the comparison is at-or-after, so at exactly the termination instant the transit ends and one second earlier it does not.

    Design: Corner/endpoints/transit_sweep_ends_only_the_certificates_whose_storage_window_has_closed
    """
    env = _build_two_transit_windows(api)
    assert_instant(env["certificate_early"]["transit_termination_at"],
                   EARLY_TRANSIT_TERMINATION, "early.transit_termination_at")
    assert_instant(env["certificate_late"]["transit_termination_at"],
                   EXPECTED_TRANSIT_TERMINATION, "late.transit_termination_at")

    set_clock(api, "2026-09-20T00:00:00Z")
    validate_success(api.run_transit_sweep(env["policy_id"], UNDERWRITER))

    still_issued = assert_total_count(
        api.list_certificates(
            UNDERWRITER, {"open_policy_id": env["policy_id"], "status": "ISSUED"}),
        1, "certificates still on risk")
    assert collect_ids(still_issued) == [env["certificate_late_id"]]

    swept = read_certificate(api, env["certificate_early_id"])
    assert swept["status"] == "TRANSIT_ENDED"
    running = read_certificate(api, env["certificate_late_id"])
    assert running["status"] == "ISSUED", (
        "a certificate whose storage window is still open is not swept"
    )


def test_sweep_expires_the_policy_only_once_the_clock_reaches_its_expiry(
        api: ApiClient) -> None:
    """
    The sweep that ends a transit before `expiry_at` leaves the cover `ACTIVE`,
    and a later sweep past `expiry_at` expires it and ends the last transit.

    The passage of time drives `ACTIVE → EXPIRED`: an `Underwriter` or a `ComplianceOfficer` may run a transit sweep on the policy, and if the logical clock has reached or passed `expiry_at` the policy's `status` becomes `EXPIRED` and its `version` increments.

    Design: Corner/endpoints/transit_sweep_ends_only_the_certificates_whose_storage_window_has_closed
    """
    env = _build_two_transit_windows(api)

    set_clock(api, "2026-09-20T00:00:00Z")
    first_sweep = validate_success(
        api.run_transit_sweep(env["policy_id"], UNDERWRITER))
    assert first_sweep["status"] == "ACTIVE", (
        "2026-09-20 is before the 2027-01-01 expiry, so the cover keeps running"
    )

    set_clock(api, "2027-01-02T00:00:00Z")
    second_sweep = validate_success(
        api.run_transit_sweep(env["policy_id"], COMPLIANCE_OFFICER))
    assert second_sweep["status"] == "EXPIRED"
    assert_version_incremented(second_sweep["version"], first_sweep["version"])

    assert_total_count(
        api.list_certificates(
            UNDERWRITER,
            {"open_policy_id": env["policy_id"], "status": "TRANSIT_ENDED"}),
        2, "certificates whose transit has ended")


def test_swept_certificates_release_their_ledger_rows_as_transit_ended(
        api: ApiClient) -> None:
    """
    Sweeping a closed transit releases its three ledger rows with the
    `TRANSIT_ENDED` reason and drops the vessel and port exposures.

    Each swept certificate's `ACTIVE` accumulation rows become `RELEASED` with `release_reason` `TRANSIT_ENDED` and the vessel and port ledgers fall accordingly.

    Design: Corner/endpoints/transit_sweep_ends_only_the_certificates_whose_storage_window_has_closed
    """
    env = _build_two_transit_windows(api)
    assert_money(read_vessel(api, env["vessel_id"])["accumulated_insured_value"],
                 2 * EXPECTED_INSURED_VALUE_CIF, "vessel exposure before the sweep")

    set_clock(api, "2026-09-20T00:00:00Z")
    validate_success(api.run_transit_sweep(env["policy_id"], UNDERWRITER))

    released = assert_total_count(
        api.list_accumulation_entries(
            UNDERWRITER, {"certificate_id": env["certificate_early_id"],
                          "status": "RELEASED"}),
        3, "released rows of the swept certificate")
    for row in released:
        assert row["release_reason"] == "TRANSIT_ENDED", (
            f"{row['scope_type']} row must be released as TRANSIT_ENDED"
        )
    assert_money(read_vessel(api, env["vessel_id"])["accumulated_insured_value"],
                 EXPECTED_INSURED_VALUE_CIF, "vessel exposure after one release")

    set_clock(api, "2027-01-02T00:00:00Z")
    validate_success(api.run_transit_sweep(env["policy_id"], COMPLIANCE_OFFICER))
    assert_money(read_vessel(api, env["vessel_id"])["accumulated_insured_value"],
                 0.00, "vessel exposure after both releases")
    assert_money(read_port(api, env["loading_port_id"])["accumulated_insured_value"],
                 0.00, "loading port exposure after both releases")
    assert_money(read_port(api, env["discharge_port_id"])["accumulated_insured_value"],
                 0.00, "discharge port exposure after both releases")


def test_delivery_cannot_be_confirmed_before_the_goods_have_sailed(
        api: ApiClient) -> None:
    """
    At 2026-08-01, nine days before cover attaches, the assured's delivery
    confirmation is refused and the certificate keeps its pinned window.

    It requires the certificate to be `ISSUED` and the logical clock to have reached or passed `attachment_at` — goods cannot be delivered before they sail.

    Design: Corner/endpoints/confirm_delivery_before_attachment_is_refused_then_accepted_after_it
    """
    env = _build_one_issued_shipment(api)
    issued = read_certificate(api, env["certificate_id"])
    assert_instant(issued["attachment_at"], SAILING_AT, "attachment_at")
    assert_instant(issued["transit_termination_at"],
                   EXPECTED_TRANSIT_TERMINATION, "transit_termination_at")

    validate_error(
        api.confirm_delivery(env["certificate_id"], env["assured"]),
        ERR_INVALID_STATE)

    unchanged = read_certificate(api, env["certificate_id"])
    assert unchanged["status"] == "ISSUED"
    assert_instant(unchanged["transit_termination_at"],
                   EXPECTED_TRANSIT_TERMINATION, "transit_termination_at")
    assert unchanged["version"] == issued["version"], (
        "a refused confirmation must leave the certificate entirely untouched"
    )
    assert_total_count(
        api.list_accumulation_entries(
            UNDERWRITER, {"certificate_id": env["certificate_id"],
                          "status": "ACTIVE"}),
        3, "still-active ledger rows")


def test_delivery_after_attachment_pulls_the_termination_instant_back(
        api: ApiClient) -> None:
    """
    A delivery reported on 2026-08-15 replaces the theoretical 2026-10-05
    storage deadline with the real delivery instant.

    The optional `delivered_at` instant may be supplied; when it is earlier than the pinned value, `transit_termination_at` is pulled back to it, so the exposure window closes at the real delivery rather than at the theoretical storage deadline.

    Design: Corner/endpoints/confirm_delivery_before_attachment_is_refused_then_accepted_after_it
    """
    env = _build_one_issued_shipment(api)
    delivered_at = "2026-08-15T00:00:00Z"
    set_clock(api, delivered_at)

    confirmed = validate_success(api.confirm_delivery(
        env["certificate_id"], env["assured"], {"delivered_at": delivered_at}))
    assert_instant(confirmed["transit_termination_at"], delivered_at,
                   "transit_termination_at")

    stored = read_certificate(api, env["certificate_id"])
    assert_instant(stored["transit_termination_at"], delivered_at,
                   "the persisted transit_termination_at")
    assert_instant(stored["attachment_at"], SAILING_AT, "attachment_at")


def test_confirmed_delivery_releases_every_ledger_row_it_booked(
        api: ApiClient) -> None:
    """
    Confirming delivery ends the transit, releases all three ledger rows as
    `DELIVERY_CONFIRMED` and empties the hull and both port ledgers.

    The certificate moves to `TRANSIT_ENDED`, its `ACTIVE` accumulation rows become `RELEASED` with `release_reason` `DELIVERY_CONFIRMED`, both ledgers fall, and the certificate's `version` increments.

    Design: Corner/endpoints/confirm_delivery_before_attachment_is_refused_then_accepted_after_it
    """
    env = _build_one_issued_shipment(api)
    before = read_certificate(api, env["certificate_id"])
    set_clock(api, "2026-08-15T00:00:00Z")

    confirmed = validate_success(api.confirm_delivery(
        env["certificate_id"], env["assured"],
        {"delivered_at": "2026-08-15T00:00:00Z"}))
    assert confirmed["status"] == "TRANSIT_ENDED"
    assert_version_incremented(confirmed["version"], before["version"])

    released = assert_total_count(
        api.list_accumulation_entries(
            UNDERWRITER, {"certificate_id": env["certificate_id"]}),
        3, "ledger rows of the delivered certificate")
    for scope in LEDGER_SCOPES:
        row = find_row(released, scope_type=scope)
        assert row["status"] == "RELEASED"
        assert row["release_reason"] == "DELIVERY_CONFIRMED", (
            f"the {scope} row must name the delivery as its release reason"
        )

    assert_money(read_vessel(api, env["vessel_id"])["accumulated_insured_value"],
                 0.00, "vessel exposure after delivery")
    assert_money(read_port(api, env["loading_port_id"])["accumulated_insured_value"],
                 0.00, "loading port exposure after delivery")
    assert_money(read_port(api, env["discharge_port_id"])["accumulated_insured_value"],
                 0.00, "discharge port exposure after delivery")


def test_terminated_war_axis_refuses_a_shipment_that_still_asks_for_war(
        api: ApiClient) -> None:
    """
    Once Rotterdam is listed the cover's war axis is gone, so a draft asking for
    war and strikes cover cannot be issued even on a current policy version.

    Then war cover: if the policy's `war_cover_status` is `TERMINATED` and this shipment asks for war or strikes cover, the issue is refused with `ERR_WAR_COVER_TERMINATED` (HTTP 409).

    Design: Corner/errors/war_cover_terminated_blocks_new_war_lines_and_premature_reinstatement
    """
    env = _build_war_terminated_book(api)
    draft_id = env["draft_w2"]["id"]

    validate_error(
        api.issue_certificate(
            draft_id,
            {"expected_open_policy_version": policy_version(api, env["policy_id"])},
            UNDERWRITER),
        ERR_WAR_COVER_TERMINATED)

    refused = read_certificate(api, draft_id)
    assert refused["status"] == "DRAFT"
    assert refused["war_cover_status"] == "PENDING"
    assert refused["effective_rate_per_mille"] is None, (
        "a refused issue must not price the shipment"
    )
    assert_total_count(
        api.list_accumulation_entries(
            UNDERWRITER, {"certificate_id": draft_id}), 0,
        "ledger rows of a refused issue")


def test_war_cover_cannot_be_reinstated_while_the_listed_port_stays_listed(
        api: ApiClient) -> None:
    """
    A reinstatement offered at 0.400 per mille is refused while Rotterdam is
    still a listed area, and the cover's war axis is left as it was.

    Reinstatement is refused with `ERR_WAR_COVER_TERMINATED` while the port whose listing caused the termination, the one recorded in `war_termination_port_unlocode`, is still in tier `LISTED_AREA`; the tier must come down before the cover can go back up.

    Design: Corner/errors/war_cover_terminated_blocks_new_war_lines_and_premature_reinstatement
    """
    env = _build_war_terminated_book(api)
    terminated = env["policy"]

    validate_error(
        api.reinstate_war_cover(env["policy_id"],
                                {"reinstatement_rate_per_mille": 0.400},
                                COMPLIANCE_OFFICER),
        ERR_WAR_COVER_TERMINATED)

    unchanged = read_policy(api, env["policy_id"])
    assert unchanged["war_cover_status"] == "TERMINATED"
    assert unchanged["war_termination_port_unlocode"] == PORT_NLRTM["unlocode"]
    assert unchanged["reinstatement_rate_per_mille"] is None, (
        "a refused reinstatement must not store the offered rate"
    )
    assert unchanged["version"] == terminated["version"], (
        "a refused reinstatement must not move the policy version"
    )


def test_a_shipment_that_buys_no_war_still_issues_under_a_terminated_axis(
        api: ApiClient) -> None:
    """
    The refusal is aimed only at war and strikes: a marine-only shipment issues
    normally with both war and strikes components at 0.00.

    It becomes `NOT_TAKEN` — a terminal state for that axis — when `war_cover_requested` is false, in which case `war_premium_amount` is 0.00, and equally when war cover was requested but a nominated port sits in `LISTED_AREA`, where no war cover is obtainable at any price.

    Design: Corner/errors/war_cover_terminated_blocks_new_war_lines_and_premature_reinstatement
    """
    env = _build_war_terminated_book(api)

    issued = issue_certificate(api, env["draft_w3"]["id"], env["policy_id"])
    assert issued["status"] == "ISSUED"
    assert issued["war_cover_status"] == "NOT_TAKEN"
    assert_money(issued["war_premium_amount"], 0.00, "war_premium_amount")
    assert_money(issued["strikes_premium_amount"], 0.00,
                 "strikes_premium_amount")
    assert_money(issued["base_premium_amount"], EXPECTED_BASE_PREMIUM,
                 "base_premium_amount")
    assert_money(issued["total_premium_amount"], EXPECTED_BASE_PREMIUM,
                 "total_premium_amount")


def test_security_calls_are_refused_on_a_voyage_with_no_live_certificate(
        api: ApiClient) -> None:
    """
    The 2026-08-25 conveyance carries only a draft, so the average declared over
    it has nobody to call security from.

    The adjuster then issues the security calls, which requires the event to be `DECLARED` and requires contributors to exist: at least one certificate on the same vessel whose `sailing_date` equals the event's `voyage_sailing_date` must be in `status` `ISSUED` or `CLAIMED`, otherwise the call is refused with `ERR_NO_CONTRIBUTING_CERTIFICATES` (HTTP 422).

    Design: Corner/errors/general_average_security_calls_on_a_voyage_with_no_live_certificate
    """
    env = _build_ga_voyages(api)
    event_id = env["event_wrong"]["id"]
    assert env["certificate_v2"]["status"] == "DRAFT"

    validate_error(api.issue_ga_security_calls(event_id, CLAIMS_ADJUSTER),
                   ERR_NO_CONTRIBUTING_CERTIFICATES)

    refused = validate_success(api.get_ga_event(event_id, CLAIMS_ADJUSTER))
    assert refused["status"] == "DECLARED", (
        "a refused call must leave the event in DECLARED"
    )
    assert refused["version"] == env["event_wrong"]["version"]
    assert_total_count(
        api.list_ga_security_postings(CLAIMS_ADJUSTER, {"ga_event_id": event_id}),
        0, "postings raised by a refused call")


def test_security_calls_succeed_on_the_voyage_that_carries_the_issued_line(
        api: ApiClient) -> None:
    """
    The same hull's 2026-08-10 conveyance carries one issued line of 1155000.00,
    so the call prices an allowance of 157500.00 at a rate of 0.136364.

    Then `contribution_rate` is the total allowance divided by the total contributory value, rounded half up to 6 decimals before it is applied to anybody.

    Design: Corner/errors/general_average_security_calls_on_a_voyage_with_no_live_certificate
    """
    env = _build_ga_voyages(api)

    called = validate_success(
        api.issue_ga_security_calls(env["event_right"]["id"], CLAIMS_ADJUSTER))
    assert called["status"] == "SECURITY_COLLECTING"
    assert_money(called["total_allowance_amount"], GA_TOTAL_ALLOWANCE_ONE_LINE,
                 "total_allowance_amount")
    assert_money(called["total_contributory_value"], EXPECTED_INSURED_VALUE_CIF,
                 "total_contributory_value")
    assert_ratio(called["contribution_rate"], GA_RATE_ONE_LINE,
                 "contribution_rate")
    assert called["postings_required_count"] == 1
    assert called["postings_posted_count"] == 0


def test_the_only_contributor_absorbs_the_whole_residual_cent_difference(
        api: ApiClient) -> None:
    """
    A single contributor is the first bucket of the ordering, so its raw
    157500.42 is corrected to the allowance itself.

    The contributors are ordered by contributory value descending, ties broken by `created_at` ascending, and the whole residual — the total allowance minus the sum of the raw contributions, which may be positive or negative — is applied to the **first** bucket of that ordering.

    Design: Corner/errors/general_average_security_calls_on_a_voyage_with_no_live_certificate
    """
    env = _build_ga_voyages(api)
    validate_success(
        api.issue_ga_security_calls(env["event_right"]["id"], CLAIMS_ADJUSTER))

    postings = assert_total_count(
        api.list_ga_security_postings(
            CLAIMS_ADJUSTER, {"ga_event_id": env["event_right"]["id"]}),
        1, "postings raised for the live conveyance")
    posting = find_row(postings, certificate_id=env["certificate_v1"]["id"])
    assert posting["status"] == "REQUIRED"
    assert_money(posting["contributory_value"], EXPECTED_INSURED_VALUE_CIF,
                 "contributory_value")
    assert_money(posting["contribution_amount"], GA_TOTAL_ALLOWANCE_ONE_LINE,
                 "contribution_amount after the residual lands")
    assert_money(
        sum(float(row["contribution_amount"]) for row in postings),
        GA_TOTAL_ALLOWANCE_ONE_LINE,
        "sum of the called contributions")


def test_two_declarations_on_one_hull_hold_it_twice_over(
        api: ApiClient) -> None:
    """
    Each average declared on the hull increments its hold counter, so two
    declarations leave the count at two and the hull under hold.

    Declaring the act immediately puts the hull under hold: the vessel's `open_ga_event_count` increments and its `status` moves `APPROVED → GA_HOLD` or `OVERAGE_SURCHARGED → GA_HOLD`, so no further certificate can be issued on that hull until the adjustment closes.

    Design: Corner/errors/general_average_security_calls_on_a_voyage_with_no_live_certificate
    """
    env = _build_ga_voyages(api)

    hull = read_vessel(api, env["vessel_id"])
    assert hull["status"] == "GA_HOLD"
    assert hull["open_ga_event_count"] == 2, (
        "both declarations must be counted against the hull"
    )


def test_enum_fields_outside_their_vocabulary_are_rejected_as_invalid_request(
        api: ApiClient) -> None:
    """
    A war risk tier of RED and a susceptibility rating of S5 are outside their
    declared vocabularies, and neither row is written.

    Schema validation itself precedes all of this and reports `ERR_INVALID_REQUEST` (HTTP 400): every non-optional input field of the endpoint must be present, enum-typed fields must hold one of their declared values, money fields must be non-negative where declared so, datetimes must parse as ISO 8601 UTC, and pagination bounds must hold.

    Design: Corner/errors/unknown_enums_bad_pagination_and_negative_money_are_rejected_as_invalid_request
    """
    good_port = create_port(api, PORT_SGSIN)

    validate_error(
        api.create_port({**PORT_USNYC, "war_risk_tier": "RED"}, UNDERWRITER),
        ERR_INVALID_REQUEST)
    validate_error(
        api.create_commodity_class(
            {**COMMODITY_CLASS_ELECTRONICS, "susceptibility_rating": "S5"},
            UNDERWRITER),
        ERR_INVALID_REQUEST)

    ports = assert_total_count(api.list_ports(UNDERWRITER), 1,
                               "ports surviving the refused registrations")
    assert collect_ids(ports) == [good_port["id"]]
    assert_total_count(api.list_commodity_classes(UNDERWRITER), 0,
                       "commodity classes surviving the refused registration")


def test_negative_money_and_an_unparseable_instant_are_rejected_as_invalid_request(
        api: ApiClient) -> None:
    """
    A duty amount of -1 and a sailing date of 2026-13-45 are both payload faults,
    so no shipment is declared at all.

    Schema validation itself precedes all of this and reports `ERR_INVALID_REQUEST` (HTTP 400): every non-optional input field of the endpoint must be present, enum-typed fields must hold one of their declared values, money fields must be non-negative where declared so, datetimes must parse as ISO 8601 UTC, and pagination bounds must hold.

    Design: Corner/errors/unknown_enums_bad_pagination_and_negative_money_are_rejected_as_invalid_request
    """
    env = build_canonical_environment(api)
    assured = make_assured_headers(env["policy_id"])
    declaration = {
        **CERTIFICATE_CIF_SHIPMENT,
        "open_policy_id": env["policy_id"],
        "commodity_class_id": env["commodity_class_id"],
        "vessel_id": env["vessel_id"],
        "loading_port_id": env["loading_port_id"],
        "discharge_port_id": env["discharge_port_id"],
    }

    validate_error(
        api.create_certificate({**declaration, "duty_amount": -1}, assured),
        ERR_INVALID_REQUEST)
    validate_error(
        api.create_certificate(
            {**declaration, "certificate_number": "CERT-BAD-DATE",
             "sailing_date": "2026-13-45T00:00:00Z"}, assured),
        ERR_INVALID_REQUEST)

    assert_total_count(
        api.list_certificates(UNDERWRITER, {"open_policy_id": env["policy_id"]}),
        0, "certificates written by refused declarations")


def test_pagination_bounds_are_enforced_at_one_and_at_one_hundred(
        api: ApiClient) -> None:
    """
    A limit of 0 or 101 and a negative offset are refused, while a limit of
    exactly 100 is inside the band and reads the collection.

    A `limit` below 1 or above 100, or a negative `offset`, is a payload fault and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

    Design: Corner/errors/unknown_enums_bad_pagination_and_negative_money_are_rejected_as_invalid_request
    """
    good_port = create_port(api, PORT_SGSIN)

    for params in ({"limit": 101}, {"limit": 0}, {"offset": -1}):
        validate_error(api.list_ports(UNDERWRITER, params), ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api.list_ports(UNDERWRITER, {"limit": 100}))
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert collect_ids(rows) == [good_port["id"]]
