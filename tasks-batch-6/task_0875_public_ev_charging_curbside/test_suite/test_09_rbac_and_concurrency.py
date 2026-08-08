"""RBAC boundaries and optimistic-concurrency (stale-version) rejections.

Corner: rbac/{driver_cannot_create_station...,host_operator_cannot_counter...},
cross_cutting/{rebate_create_stale_station...,statement_create_stale_site...}.
"""
from test_helpers import (
    validate_success, validate_error,
    admin_headers, make_driver_headers, make_host_operator_headers,
    create_station_payload, create_rebate_claim_payload, create_revenue_statement_payload,
    new_site, new_agreement, setup_grant_station_for_claim, get_site_version,
)


# --------------------------------------------------------------------------- #
# rbac / driver_cannot_create_station_returns_unauthorized
# --------------------------------------------------------------------------- #
def test_driver_cannot_create_station(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted
    to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    POST /stations is authorized for ProgramAdmin only.

    Design: Corner/rbac/driver_cannot_create_station_returns_unauthorized
    """
    site = new_site()
    res = api.create_station(create_station_payload(site["id"]), make_driver_headers("drv-1"))
    validate_error(res, "ERR_UNAUTHORIZED")


# --------------------------------------------------------------------------- #
# rbac / host_operator_cannot_counter_other_sites_agreement_returns_not_owner
# --------------------------------------------------------------------------- #
def test_host_operator_countering_other_sites_agreement_not_owner(api):
    """PRD §3.1: "a counter attempted by an operator whose `X-User-ID` is not the
    agreement's `site_id` is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/host_operator_cannot_counter_other_sites_agreement_returns_not_owner
    """
    site_a = new_site(name="Site A")
    site_b = new_site(name="Site B")
    agr = new_agreement(site_a["id"])
    validate_success(api.propose_agreement(agr["id"], {}, admin_headers()), 200)
    # foreign operator (identity = site_b) counters site_a's agreement
    res = api.counter_agreement(agr["id"], {"counter_revenue_share_pct": 0.12},
                                make_host_operator_headers(site_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


# --------------------------------------------------------------------------- #
# cross_cutting / rebate_create_stale_station_version_returns_412
# --------------------------------------------------------------------------- #
def test_rebate_create_with_stale_station_version_rejected(api):
    """PRD §2.7: "If the station's `version` has advanced since the client last read it
    — because a prior claim create bumped it, or the station was recommissioned or
    reconfigured — the create is rejected with `ERR_STALE_VERSION` (HTTP 412) ... A
    successful create increments the station's `version` by one".

    Design: Corner/cross_cutting/rebate_create_stale_station_version_returns_412
    """
    env = setup_grant_station_for_claim()
    stale_v = env["station_version"]
    validate_success(api.create_rebate_claim(
        create_rebate_claim_payload(env["station"]["id"], env["grant"]["id"], stale_v),
        admin_headers()), 201)
    # second create still carrying the previously-observed (now stale) version
    res = api.create_rebate_claim(
        create_rebate_claim_payload(env["station"]["id"], env["grant"]["id"], stale_v),
        admin_headers())
    validate_error(res, "ERR_STALE_VERSION")


# --------------------------------------------------------------------------- #
# cross_cutting / statement_create_stale_site_version_returns_412
# --------------------------------------------------------------------------- #
def test_statement_create_with_stale_site_version_rejected(api):
    """PRD §2.7: "If the site's `version` has advanced since the client last read it —
    because a prior statement generation bumped it — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412) ... A successful create increments the host site's
    `version` by one".

    Design: Corner/cross_cutting/statement_create_stale_site_version_returns_412
    """
    site = new_site()
    stale_v = get_site_version(site["id"])
    validate_success(api.create_revenue_statement(
        create_revenue_statement_payload(site["id"], stale_v, basis="GROSS"), admin_headers()), 201)
    res = api.create_revenue_statement(
        create_revenue_statement_payload(site["id"], stale_v, basis="GROSS"), admin_headers())
    validate_error(res, "ERR_STALE_VERSION")
