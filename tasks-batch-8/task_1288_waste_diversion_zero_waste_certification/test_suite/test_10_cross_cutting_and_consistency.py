"""Cross-cutting complexity layers: optimistic concurrency, close-sweep
checkpoints (lapse, contract expiry), draft supersession, approval
supersession, and immediate consistency (PRD §2.7, §3.2, §3.4, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_open_period_scenario, setup_closed_period_with_rate,
    create_site, create_vendor, create_active_contract, create_period,
    create_ticket, validate_ticket, set_clock, create_application_payload,
    ApiErrorId, TEST_USERS, make_manager_headers, make_officer_headers,
)

MGR = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]
STEWARD = TEST_USERS["steward_headers"]


def test_application_create_stale_site_version(api):
    """PRD §2.7: "A POST /certification_applications request must carry
    expected_site_version, the applicant's last-observed version of the target
    site. If the site's current version has advanced since that observation,
    the create is rejected with ERR_STALE_VERSION (HTTP 412), and the client
    must re-read the site before retrying."

    Design: Corner/cross_cutting_layers/application_create_stale_site_version
    """
    set_clock()
    site = create_site("Site OC")
    period = create_period(site["id"])
    observed_version = site["version"]  # 1
    get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], observed_version,
                                   level_requested="BRONZE"), MGR,
    ))
    # The first create bumped Site.version to 2; replaying the stale version fails.
    validate_error(
        api.create_application(
            create_application_payload(site["id"], period["id"], observed_version,
                                       level_requested="SILVER"), MGR,
        ),
        ApiErrorId.ERR_STALE_VERSION,
    )
    s = get_success_data(api.get_site(site["id"], OFFICER))
    assert s["version"] == 2


def test_certification_lapse_after_12_months(api):
    """PRD §3.8: "Approvals also age out on their own: when the close sweep of
    §3.4 finds an APPROVED application whose decided_at plus twelve calendar
    months is strictly earlier than the logical clock date, the application
    moves to LAPSED."
    PRD §3.8: "the site's certification_tier is re-derived as the level of its
    APPROVED, non-LAPSED, non-SUPERSEDED application with the greatest
    decided_at, falling back to NONE when no such application remains."

    Design: Corner/cross_cutting_layers/certification_lapse_after_12_months
    """
    site, vendor, contract, p1 = setup_closed_period_with_rate(
        "Site LP",
        tickets=[{"disposal_route": "RECYCLING", "gross_weight_lbs": 2000,
                  "tare_weight_lbs": 1000, "external_ticket_ref": "LP-T1"}],
    )
    site_now = get_success_data(api.get_site(site["id"], OFFICER))
    app = get_success_data(api.create_application(
        create_application_payload(site["id"], p1["id"], site_now["version"],
                                   level_requested="BRONZE"), MGR,
    ))
    get_success_data(api.submit_application(app["id"], make_manager_headers("mgr-1")))
    get_success_data(api.start_review(app["id"], OFFICER))
    get_success_data(api.decide_application(app["id"], {"outcome": "APPROVED"},
                                            make_officer_headers("officer-1")))
    s_before = get_success_data(api.get_site(site["id"], OFFICER))
    assert s_before["certification_tier"] == "BRONZE"
    # Advance clock past decided_at (2026-08-10) + 12 months.
    set_clock("2027-09-01T00:00:00Z")
    p2 = create_period(site["id"], period_start="2027-08-01", period_end="2027-09-01")
    get_success_data(api.close_period(p2["id"], OFFICER))
    a = get_success_data(api.get_application(app["id"], OFFICER))
    assert a["status"] == "LAPSED"
    s_after = get_success_data(api.get_site(site["id"], OFFICER))
    assert s_after["certification_tier"] == "NONE"


def test_contract_expiry_sweep_at_close(api):
    """PRD §3.4: "every contract of the site whose window_end is earlier than
    the logical clock date moves to EXPIRED, whether it was ACTIVE or
    SUSPENDED."

    Design: Corner/cross_cutting_layers/contract_expiry_sweep_at_close
    """
    site = create_site("Site EX")
    vendor = create_vendor()
    contract = create_active_contract(site["id"], vendor["id"],
                                      window_start="2026-01-01",
                                      window_end="2026-08-31")
    set_clock("2026-10-05T00:00:00Z")
    period = create_period(site["id"], period_start="2026-10-01",
                           period_end="2026-11-01")
    get_success_data(api.close_period(period["id"], OFFICER))
    c = get_success_data(api.get_contract(contract["id"], OFFICER))
    assert c["status"] == "EXPIRED"


def test_supersede_existing_draft_on_create(api):
    """PRD §3.8: "Creating the draft carries a superseding side effect: any
    existing DRAFT application of the same site for the same level moves to
    WITHDRAWN, and the site's version increments by one — which is precisely
    why the stale-version guard exists."

    Design: Corner/cross_cutting_layers/supersede_existing_draft_on_create
    """
    set_clock()
    site = create_site("Site SS")
    period = create_period(site["id"])
    app_a = get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], site["version"],
                                   level_requested="BRONZE"), MGR,
    ))
    s2 = get_success_data(api.get_site(site["id"], OFFICER))
    assert s2["version"] == 2
    app_b = get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], s2["version"],
                                   level_requested="BRONZE"), MGR,
    ))
    assert app_b["status"] == "DRAFT"
    a = get_success_data(api.get_application(app_a["id"], OFFICER))
    assert a["status"] == "WITHDRAWN"
    s3 = get_success_data(api.get_site(site["id"], OFFICER))
    assert s3["version"] == 3


def test_approved_application_supersedes_prior(api):
    """PRD §3.8: "Approval ripples outward. Any prior `APPROVED` application of
    the same site moves to `SUPERSEDED`, and the site's `certification_tier`
    becomes the newly approved application's `level_requested`."

    Design: Corner/cross_cutting_layers/approved_application_supersedes_prior
    """
    site, vendor, contract, period = setup_closed_period_with_rate(
        "Site SP",
        tickets=[{"disposal_route": "RECYCLING", "gross_weight_lbs": 2000,
                  "tare_weight_lbs": 1000, "external_ticket_ref": "SP-T1"}],
    )
    site_now = get_success_data(api.get_site(site["id"], OFFICER))
    app_a = get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], site_now["version"],
                                   level_requested="BRONZE"), MGR,
    ))
    get_success_data(api.submit_application(app_a["id"], make_manager_headers("mgr-1")))
    get_success_data(api.start_review(app_a["id"], OFFICER))
    get_success_data(api.decide_application(app_a["id"], {"outcome": "APPROVED"},
                                            make_officer_headers("officer-1")))
    s_now = get_success_data(api.get_site(site["id"], OFFICER))
    app_b = get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], s_now["version"],
                                   level_requested="SILVER"), MGR,
    ))
    get_success_data(api.submit_application(app_b["id"], make_manager_headers("mgr-1")))
    get_success_data(api.start_review(app_b["id"], OFFICER))
    decided = get_success_data(api.decide_application(
        app_b["id"], {"outcome": "APPROVED"}, make_officer_headers("officer-1")
    ))
    assert decided["status"] == "APPROVED"
    a = get_success_data(api.get_application(app_a["id"], OFFICER))
    assert a["status"] == "SUPERSEDED"
    s = get_success_data(api.get_site(site["id"], OFFICER))
    assert s["certification_tier"] == "SILVER"


def test_immediate_visibility_after_mutation(api):
    """PRD §3.3: "Validation by a DataSteward moves the ticket from PENDING to
    VALIDATED."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/immediate_visibility_after_mutation
    """
    site, vendor, contract, period = setup_open_period_scenario("Site IC2X")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       gross_weight_lbs=2000, tare_weight_lbs=1000,
                       external_ticket_ref="IC2-T1")
    resp = get_success_data(api.validate_ticket(t1["id"], STEWARD))
    assert resp["validation_status"] == "VALIDATED"
    got = get_success_data(api.get_ticket(t1["id"], STEWARD))
    assert got["validation_status"] == "VALIDATED"
