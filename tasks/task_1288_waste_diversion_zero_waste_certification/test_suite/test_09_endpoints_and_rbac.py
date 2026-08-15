"""Endpoint listing/pagination, computed reads, and RBAC denials
(PRD §2.1, §2.3, §3.3, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    setup_open_period_scenario,
    create_site, create_vendor, create_active_contract, create_period,
    create_ticket, validate_ticket, set_clock, create_application_payload,
    ApiErrorId, TEST_USERS, make_vendor_user_headers,
)

MGR = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]
STEWARD = TEST_USERS["steward_headers"]


def test_tickets_list_pagination_envelope(api):
    """PRD §2.3: "limit sets the maximum number of items returned; when omitted
    it defaults to 10, and it accepts values from a minimum of 1 to a maximum
    of 100. offset sets the number of items to skip and defaults to 0. ... The
    meta object of list responses carries the pagination fields limit, offset,
    total_count, and has_more."

    Design: Corner/endpoints/tickets_list_pagination_envelope
    """
    site = create_site("Site PG")
    vendor = create_vendor()
    contract = create_active_contract(site["id"], vendor["id"])
    for ref in ("PG-T1", "PG-T2", "PG-T3"):
        create_ticket(site["id"], vendor["id"], contract["id"],
                      gross_weight_lbs=2000, tare_weight_lbs=1000,
                      external_ticket_ref=ref)
    page1, meta1 = validate_paginated(
        api.list_tickets(STEWARD, params={"site_id": site["id"], "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0
    page2, meta2 = validate_paginated(
        api.list_tickets(STEWARD, params={"site_id": site["id"], "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert meta2["offset"] == 2


def test_tickets_filter_by_validation_status(api):
    """PRD §3.3: "Tickets may be listed with filters on `site_id`, `vendor_id`,
    `contract_id`, or `validation_status`, and fetched individually by
    `ticket_id`."

    Design: Corner/endpoints/tickets_filter_by_validation_status
    """
    site, vendor, contract, period = setup_open_period_scenario("Site FL")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       gross_weight_lbs=2000, tare_weight_lbs=1000,
                       external_ticket_ref="FL-T1")
    validate_ticket(t1["id"])
    create_ticket(site["id"], vendor["id"], contract["id"],
                  gross_weight_lbs=2000, tare_weight_lbs=1000,
                  external_ticket_ref="FL-T2")
    data, meta = validate_paginated(
        api.list_tickets(STEWARD, params={"site_id": site["id"],
                                          "validation_status": "VALIDATED"})
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == t1["id"]


def test_period_get_reflects_live_totals(api):
    """PRD §3.4: "Periods may be listed with filters on site_id and status, or
    read individually by period_id; while a period is OPEN, reads return the
    live computed totals."
    PRD §3.3: "Provisional membership does not change at validation: the
    ticket was already counted while PENDING."

    Design: Corner/endpoints/period_get_reflects_live_totals
    """
    site, vendor, contract, period = setup_open_period_scenario("Site LV")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=3000,
                       tare_weight_lbs=1000, external_ticket_ref="LV-T1")
    validate_ticket(t1["id"])
    p1 = get_success_data(api.get_period(period["id"], STEWARD))
    assert p1["diversion_rate_certified_pct"] == pytest.approx(100.00, abs=0.005)
    create_ticket(site["id"], vendor["id"], contract["id"],
                  disposal_route="LANDFILL", gross_weight_lbs=2000,
                  tare_weight_lbs=1000, external_ticket_ref="LV-T2")
    p2 = get_success_data(api.get_period(period["id"], STEWARD))
    assert p2["diversion_rate_provisional_pct"] == pytest.approx(66.67, abs=0.005)
    assert p2["diversion_rate_certified_pct"] == pytest.approx(100.00, abs=0.005)


# ============================================================ RBAC

def test_ticket_validate_forbidden_for_vendor_user(api):
    """PRD §2.1: "A request whose role is not permitted to call the target
    endpoint is rejected with ERR_FORBIDDEN (HTTP 403)."
    PRD §3.3: "Recording a load is the VendorUser's job — data stewards never
    create tickets." Validation is reserved to DataSteward per the endpoint
    table in §4 (POST /tickets/{ticket_id}/validate: DataSteward).

    Design: Corner/rbac/ticket_validate_forbidden_for_vendor_user
    """
    site = create_site("Site F1")
    vendor = create_vendor()
    contract = create_active_contract(site["id"], vendor["id"])
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       gross_weight_lbs=2000, tare_weight_lbs=1000,
                       external_ticket_ref="F1-T1")
    validate_error(
        api.validate_ticket(t1["id"], make_vendor_user_headers(vendor["id"])),
        ApiErrorId.ERR_FORBIDDEN,
    )


def test_ticket_create_vendor_mismatch_forbidden(api):
    """PRD §2.1: "When X-User-Role is VendorUser, X-User-ID is the id of the
    acting Vendor; ownership checks on any resource that references a Vendor
    compare the resource's vendor_id field to X-User-ID, and a mismatch on
    ticket operations is rejected with ERR_VENDOR_MISMATCH (HTTP 403)."

    Design: Corner/rbac/ticket_create_vendor_mismatch_forbidden
    """
    site = create_site("Site VM")
    v1 = create_vendor("HaulerOne")
    v2 = create_vendor("HaulerTwo")
    contract = create_active_contract(site["id"], v2["id"])
    validate_error(
        api.create_ticket(
            {
                "site_id": site["id"], "vendor_id": v2["id"],
                "contract_id": contract["id"], "material_stream": "MIXED_RECYCLABLES",
                "disposal_route": "RECYCLING", "gross_weight_lbs": 2000,
                "tare_weight_lbs": 1000, "ticket_date": "2026-08-05",
                "external_ticket_ref": "VM-T1",
            },
            make_vendor_user_headers(v1["id"]),
        ),
        ApiErrorId.ERR_VENDOR_MISMATCH,
    )


def test_decide_forbidden_for_sustainability_manager(api):
    """PRD §2.1: "A request whose role is not permitted to call the target
    endpoint is rejected with ERR_FORBIDDEN (HTTP 403)."
    PRD §4 table: POST /certification_applications/{application_id}/decide is
    authorized for CertificationOfficer only.

    Design: Corner/rbac/decide_forbidden_for_sustainability_manager
    """
    set_clock()
    site = create_site("Site F2")
    period = create_period(site["id"])
    app = get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], site["version"]), MGR,
    ))
    validate_error(api.decide_application(app["id"], {"outcome": "APPROVED"}, MGR),
                   ApiErrorId.ERR_FORBIDDEN)


def test_period_close_forbidden_for_data_steward(api):
    """PRD §2.1: "A request whose role is not permitted to call the target
    endpoint is rejected with ERR_FORBIDDEN (HTTP 403)."
    PRD §4 table: POST /scorecard_periods/{period_id}/close is authorized for
    CertificationOfficer only.

    Design: Corner/rbac/period_close_forbidden_for_data_steward
    """
    set_clock()
    site = create_site("Site F3")
    period = create_period(site["id"])
    validate_error(api.close_period(period["id"], STEWARD), ApiErrorId.ERR_FORBIDDEN)
