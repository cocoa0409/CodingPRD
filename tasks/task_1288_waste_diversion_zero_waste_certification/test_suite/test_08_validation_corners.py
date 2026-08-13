"""Validation corners: auth, uniqueness, weight arithmetic, stream match,
window validity, and state-gate errors (PRD §2.1, §2.8, §3.2–§3.4, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_open_period_scenario, setup_closed_period_with_rate,
    create_site, create_vendor, create_contract, create_active_contract,
    create_period, create_goal, create_ticket, validate_ticket, create_event,
    set_clock, create_application_payload,
    ApiErrorId, TEST_USERS, make_vendor_user_headers, make_manager_headers,
    make_officer_headers,
)

MGR = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]
STEWARD = TEST_USERS["steward_headers"]


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "A request with a missing header, or whose role is not one of
    these declared values, is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    site = create_site("Site AU1")
    resp = api.get_site(site["id"], headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_duplicate_ticket_ref_rejected(api):
    """PRD §3.3: "uniqueness of the pair of `vendor_id` and
    `external_ticket_ref` across that vendor's non-`VOIDED` tickets
    (`ERR_DUPLICATE_TICKET_REF`, HTTP 409)."

    Design: Corner/validations/duplicate_ticket_ref_rejected
    """
    site = create_site("Site DP")
    vendor = create_vendor()
    contract = create_active_contract(site["id"], vendor["id"])
    create_ticket(site["id"], vendor["id"], contract["id"],
                  gross_weight_lbs=2000, tare_weight_lbs=1000,
                  ticket_date="2026-08-05", external_ticket_ref="DUP-1")
    validate_error(
        api.create_ticket(
            {
                "site_id": site["id"], "vendor_id": vendor["id"],
                "contract_id": contract["id"], "material_stream": "MIXED_RECYCLABLES",
                "disposal_route": "RECYCLING", "gross_weight_lbs": 3000,
                "tare_weight_lbs": 1000, "ticket_date": "2026-08-06",
                "external_ticket_ref": "DUP-1",
            },
            make_vendor_user_headers(vendor["id"]),
        ),
        ApiErrorId.ERR_DUPLICATE_TICKET_REF,
    )


def test_invalid_weights_rejected(api):
    """PRD §3.3: "both weights positive integers with the gross strictly
    greater than the tare (ERR_INVALID_WEIGHTS, HTTP 422)."

    Design: Corner/validations/invalid_weights_rejected
    """
    site = create_site("Site IW")
    vendor = create_vendor()
    contract = create_active_contract(site["id"], vendor["id"])
    validate_error(
        api.create_ticket(
            {
                "site_id": site["id"], "vendor_id": vendor["id"],
                "contract_id": contract["id"], "material_stream": "MIXED_RECYCLABLES",
                "disposal_route": "RECYCLING", "gross_weight_lbs": 1000,
                "tare_weight_lbs": 1000, "ticket_date": "2026-08-05",
                "external_ticket_ref": "IW-T1",
            },
            make_vendor_user_headers(vendor["id"]),
        ),
        ApiErrorId.ERR_INVALID_WEIGHTS,
    )


def test_stream_contract_mismatch_rejected(api):
    """PRD §3.3: "the ticket's `material_stream` equal to the referenced
    contract's `material_stream` (`ERR_STREAM_CONTRACT_MISMATCH`, HTTP 422)."

    Design: Corner/validations/stream_contract_mismatch_rejected
    """
    site = create_site("Site SM")
    vendor = create_vendor()
    contract = create_active_contract(site["id"], vendor["id"])  # MIXED_RECYCLABLES
    validate_error(
        api.create_ticket(
            {
                "site_id": site["id"], "vendor_id": vendor["id"],
                "contract_id": contract["id"], "material_stream": "CARDBOARD",
                "disposal_route": "RECYCLING", "gross_weight_lbs": 2000,
                "tare_weight_lbs": 1000, "ticket_date": "2026-08-05",
                "external_ticket_ref": "SM-T1",
            },
            make_vendor_user_headers(vendor["id"]),
        ),
        ApiErrorId.ERR_STREAM_CONTRACT_MISMATCH,
    )


def test_segregation_of_duties_same_user_decide_forbidden(api):
    """PRD §3.8: "Segregation of duties requires the decider's X-User-ID to
    differ from the recorded submitted_by — the person who submitted an
    application may not decide it — and a self-decision is rejected with
    ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

    Design: Corner/validations/segregation_of_duties_same_user_decide_forbidden
    """
    site, vendor, contract, period = setup_closed_period_with_rate(
        "Site SD",
        tickets=[{"disposal_route": "RECYCLING", "gross_weight_lbs": 2000,
                  "tare_weight_lbs": 1000, "external_ticket_ref": "SD-T1"}],
    )
    site_now = get_success_data(api.get_site(site["id"], OFFICER))
    app = get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], site_now["version"]), MGR,
    ))
    get_success_data(api.submit_application(app["id"], make_manager_headers("shared-1")))
    get_success_data(api.start_review(app["id"], make_officer_headers("officer-9")))
    # "shared-1" submitted; a decide attempt by the same user id is forbidden,
    # even under the (correct) CertificationOfficer role.
    validate_error(
        api.decide_application(app["id"], {"outcome": "APPROVED"},
                               make_officer_headers("shared-1")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    a = get_success_data(api.get_application(app["id"], OFFICER))
    assert a["status"] == "UNDER_REVIEW"


def test_threshold_not_met_8999_rejected(api):
    """PRD §3.8: "the reporting period's frozen diversion_rate_certified_pct
    must meet the requested level's threshold — 50.0 for BRONZE, 70.0 for
    SILVER, 85.0 for GOLD, and 90.0 for ZERO_WASTE — compared with the
    boundary inclusive and with no further rounding at decision time, so
    exactly 90.00 earns ZERO_WASTE; a shortfall is rejected with
    ERR_CERTIFICATION_THRESHOLD_NOT_MET (HTTP 422)."

    Design: Corner/validations/threshold_not_met_8999_rejected
    """
    # 8999 diverted of 10000 total -> certified rate 89.99
    site, vendor, contract, period = setup_closed_period_with_rate(
        "Site 89",
        tickets=[
            {"disposal_route": "RECYCLING", "gross_weight_lbs": 9000,
             "tare_weight_lbs": 1, "external_ticket_ref": "89-T1"},
            {"disposal_route": "LANDFILL", "gross_weight_lbs": 1002,
             "tare_weight_lbs": 1, "external_ticket_ref": "89-T2"},
        ],
    )
    p = get_success_data(api.get_period(period["id"], OFFICER))
    assert p["diversion_rate_certified_pct"] == pytest.approx(89.99, abs=0.005)
    site_now = get_success_data(api.get_site(site["id"], OFFICER))
    app = get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], site_now["version"],
                                   level_requested="ZERO_WASTE"), MGR,
    ))
    get_success_data(api.submit_application(app["id"], make_manager_headers("mgr-1")))
    get_success_data(api.start_review(app["id"], OFFICER))
    validate_error(
        api.decide_application(app["id"], {"outcome": "APPROVED"},
                               make_officer_headers("officer-1")),
        ApiErrorId.ERR_CERTIFICATION_THRESHOLD_NOT_MET,
    )
    a = get_success_data(api.get_application(app["id"], OFFICER))
    assert a["status"] == "UNDER_REVIEW"


def test_submit_blocked_on_probation_standing(api):
    """PRD §3.8: "the site's `program_standing` must not be `PROBATION`
    (`ERR_STANDING_PROBATION`, HTTP 409)."

    Design: Corner/validations/submit_blocked_on_probation_standing
    """
    set_clock()
    site = create_site("Site PB")
    period = create_period(site["id"])
    get_success_data(api.close_period(period["id"], OFFICER))
    create_event(site["id"], event_date="2026-08-05",
                 material_stream="MIXED_RECYCLABLES", contamination_pct=15)
    site_now = get_success_data(api.get_site(site["id"], OFFICER))
    assert site_now["program_standing"] == "PROBATION"
    app = get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], site_now["version"]), MGR,
    ))
    validate_error(api.submit_application(app["id"], MGR),
                   ApiErrorId.ERR_STANDING_PROBATION)
    a = get_success_data(api.get_application(app["id"], OFFICER))
    assert a["status"] == "DRAFT"


def test_validate_without_open_period_returns_no_open_period(api):
    """PRD §3.3: "an OPEN scorecard period of the site must contain the
    ticket_date within its half-open window (ERR_NO_OPEN_PERIOD, HTTP 409)."

    Design: Corner/validations/validate_without_open_period_returns_no_open_period
    """
    site, vendor, contract, period = setup_open_period_scenario("Site NP")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       ticket_date="2026-07-15", gross_weight_lbs=2000,
                       tare_weight_lbs=1000, external_ticket_ref="NP-T1")
    validate_error(api.validate_ticket(t1["id"], STEWARD),
                   ApiErrorId.ERR_NO_OPEN_PERIOD)
    t = get_success_data(api.get_ticket(t1["id"], OFFICER))
    assert t["validation_status"] == "PENDING"


def test_validate_future_dated_ticket_rejected(api):
    """PRD §3.3: "the ticket_date must not be later than the logical clock
    date (ERR_TICKET_DATE_FUTURE, HTTP 422)."

    Design: Corner/validations/validate_future_dated_ticket_rejected
    """
    site, vendor, contract, period = setup_open_period_scenario("Site FD")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       ticket_date="2026-08-20", gross_weight_lbs=2000,
                       tare_weight_lbs=1000, external_ticket_ref="FD-T1")
    validate_error(api.validate_ticket(t1["id"], STEWARD),
                   ApiErrorId.ERR_TICKET_DATE_FUTURE)


def test_close_with_pending_tickets_rejected(api):
    """PRD §3.4: "Closing a period is a CertificationOfficer action with two
    preconditions: the period must be OPEN, otherwise ERR_INVALID_STATE, and
    no PENDING ticket of the site may have a ticket_date inside the window,
    otherwise ERR_PERIOD_HAS_PENDING_TICKETS (HTTP 409)."

    Design: Corner/validations/close_with_pending_tickets_rejected
    """
    site, vendor, contract, period = setup_open_period_scenario("Site PT")
    create_ticket(site["id"], vendor["id"], contract["id"],
                  gross_weight_lbs=2000, tare_weight_lbs=1000,
                  external_ticket_ref="PT-T1")
    validate_error(api.close_period(period["id"], OFFICER),
                   ApiErrorId.ERR_PERIOD_HAS_PENDING_TICKETS)
    p = get_success_data(api.get_period(period["id"], OFFICER))
    assert p["status"] == "OPEN"


def test_second_open_period_rejected(api):
    """PRD §3.4: "if the site already has an OPEN period the request is
    rejected with ERR_PERIOD_ALREADY_OPEN (HTTP 409); only if that guard
    passes does the overlap guard fire — no other period of the site, whatever
    its status, may overlap the half-open window, or the create fails with
    ERR_PERIOD_OVERLAP (HTTP 409)."

    Design: Corner/validations/second_open_period_rejected
    """
    set_clock()
    site = create_site("Site PO")
    p1 = create_period(site["id"], period_start="2026-08-01", period_end="2026-09-01")
    validate_error(
        api.create_period({"site_id": site["id"], "period_start": "2026-08-15",
                           "period_end": "2026-10-01"}, OFFICER),
        ApiErrorId.ERR_PERIOD_ALREADY_OPEN,
    )
    get_success_data(api.close_period(p1["id"], OFFICER))
    validate_error(
        api.create_period({"site_id": site["id"], "period_start": "2026-08-15",
                           "period_end": "2026-10-01"}, OFFICER),
        ApiErrorId.ERR_PERIOD_OVERLAP,
    )


def test_cross_site_event_ticket_reference_rejected(api):
    """PRD §3.5: "A linked ticket must belong to the event's site, otherwise
    ERR_CROSS_SITE_REFERENCE."

    Design: Corner/validations/cross_site_event_ticket_reference_rejected
    """
    set_clock()
    site_a = create_site("Site A")
    site_b = create_site("Site B")
    vendor = create_vendor()
    contract = create_active_contract(site_b["id"], vendor["id"])
    period_b = create_period(site_b["id"])
    tb = create_ticket(site_b["id"], vendor["id"], contract["id"],
                       gross_weight_lbs=2000, tare_weight_lbs=1000,
                       external_ticket_ref="XS-T1")
    validate_ticket(tb["id"])
    validate_error(
        api.create_contamination_event(
            {"site_id": site_a["id"], "event_date": "2026-08-06",
             "material_stream": "MIXED_RECYCLABLES", "contamination_pct": 3,
             "ticket_id": tb["id"]},
            TEST_USERS["auditor_headers"],
        ),
        ApiErrorId.ERR_CROSS_SITE_REFERENCE,
    )


def test_goal_invalid_window_rejected(api):
    """PRD §3.6: "a half-open window running from window_start inclusive to
    window_end exclusive; the start must be strictly earlier than the end,
    otherwise ERR_WINDOW_INVALID."

    Design: Corner/validations/goal_invalid_window_rejected
    """
    site = create_site("Site GW")
    validate_error(
        api.create_goal(
            {"site_id": site["id"], "metric": "DIVERSION_RATE", "target_value": 80,
             "window_start": "2026-06-01", "window_end": "2026-06-01"}, MGR,
        ),
        ApiErrorId.ERR_WINDOW_INVALID,
    )


def test_resubmit_pending_ticket_rejected(api):
    """PRD §3.3: "a `VendorUser` may resubmit a `REJECTED` ticket — only from
    `REJECTED`, otherwise `ERR_TICKET_NOT_REJECTED`."

    Design: Corner/validations/resubmit_pending_ticket_rejected
    """
    site = create_site("Site RP")
    vendor = create_vendor()
    contract = create_active_contract(site["id"], vendor["id"])
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       gross_weight_lbs=2000, tare_weight_lbs=1000,
                       external_ticket_ref="RP-T1")
    validate_error(
        api.resubmit_ticket(t1["id"], {"gross_weight_lbs": 2500},
                            make_vendor_user_headers(vendor["id"])),
        ApiErrorId.ERR_TICKET_NOT_REJECTED,
    )


def test_void_pending_ticket_rejected(api):
    """PRD §3.3: "A `DataSteward` may void a ticket, optionally attaching a
    `reason`, only from `VALIDATED` — otherwise `ERR_TICKET_NOT_VALIDATED`."

    Design: Corner/validations/void_pending_ticket_rejected
    """
    site = create_site("Site VP")
    vendor = create_vendor()
    contract = create_active_contract(site["id"], vendor["id"])
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       gross_weight_lbs=2000, tare_weight_lbs=1000,
                       external_ticket_ref="VP-T1")
    validate_error(api.void_ticket(t1["id"], {"reason": "premature"}, STEWARD),
                   ApiErrorId.ERR_TICKET_NOT_VALIDATED)


def test_create_ticket_on_draft_contract_rejected(api):
    """PRD §3.3: "the ticket's `material_stream` equal to the referenced
    contract's `material_stream` (`ERR_STREAM_CONTRACT_MISMATCH`, HTTP 422);
    the contract `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`, HTTP 409)."

    Design: Corner/validations/create_ticket_on_draft_contract_rejected
    """
    site = create_site("Site DC")
    vendor = create_vendor()
    contract = create_contract(site["id"], vendor["id"])  # stays DRAFT
    validate_error(
        api.create_ticket(
            {
                "site_id": site["id"], "vendor_id": vendor["id"],
                "contract_id": contract["id"], "material_stream": "MIXED_RECYCLABLES",
                "disposal_route": "RECYCLING", "gross_weight_lbs": 2000,
                "tare_weight_lbs": 1000, "ticket_date": "2026-08-05",
                "external_ticket_ref": "DC-T1",
            },
            make_vendor_user_headers(vendor["id"]),
        ),
        ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
    )


def test_activate_over_cap_rate_rejected(api):
    """PRD §3.2: "Fourth, the fiscal guard: `rebate_per_ton_cents` must not
    exceed the site's `max_rebate_rate_per_ton_cents` policy cap, or
    activation is rejected with `ERR_REBATE_RATE_CAP_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/activate_over_cap_rate_rejected
    """
    site = create_site("Site RC")
    vendor = create_vendor()
    c = create_contract(site["id"], vendor["id"], material_stream="COMPOST_ORGANICS",
                        rebate_per_ton_cents=15000)
    validate_error(api.activate_contract(c["id"], MGR),
                   ApiErrorId.ERR_REBATE_RATE_CAP_EXCEEDED)
    assert get_success_data(api.get_contract(c["id"], OFFICER))["status"] == "DRAFT"


def test_double_submit_rejected(api):
    """PRD §3.8: "Submission moves the application from DRAFT to SUBMITTED
    through four gates, evaluated in order: the application must be DRAFT
    (ERR_APPLICATION_NOT_DRAFT)."

    Design: Corner/validations/double_submit_rejected
    """
    set_clock()
    site = create_site("Site DS")
    period = create_period(site["id"])
    get_success_data(api.close_period(period["id"], OFFICER))
    site_now = get_success_data(api.get_site(site["id"], OFFICER))
    app = get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], site_now["version"]), MGR,
    ))
    get_success_data(api.submit_application(app["id"], make_manager_headers("mgr-1")))
    validate_error(api.submit_application(app["id"], make_manager_headers("mgr-1")),
                   ApiErrorId.ERR_APPLICATION_NOT_DRAFT)


def test_start_review_on_draft_rejected(api):
    """PRD §3.8: "A CertificationOfficer then takes the application from
    SUBMITTED to UNDER_REVIEW; attempted from any other state, this step is
    rejected with ERR_APPLICATION_NOT_SUBMITTED."

    Design: Corner/validations/start_review_on_draft_rejected
    """
    set_clock()
    site = create_site("Site SR")
    period = create_period(site["id"])
    app = get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], site["version"]), MGR,
    ))
    validate_error(api.start_review(app["id"], OFFICER),
                   ApiErrorId.ERR_APPLICATION_NOT_SUBMITTED)
