"""Optimistic concurrency, logical-clock default epoch, and RBAC denials."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    set_clock, create_principal, create_port_call, create_da_for_call,
    create_vendor, create_service_order, create_crew_change, create_notification,
    create_berth_window,
    make_agency_ops_headers, make_agency_admin_headers, make_agency_finance_headers,
    make_port_authority_headers, make_principal_rep_headers,
    make_vendor_rep_headers, make_crewing_agent_headers,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_layers / occ_portcall_patch_stale_version
# ---------------------------------------------------------------------------

def test_occ_portcall_patch_stale_version(api):
    """PRD §2.8: "A port-call schedule patch must likewise carry
    `expected_port_call_version`, because schedule edits legitimately
    overwrite the same ETA/ETD fields and the check forces the second writer
    to re-read. In both cases, if the supplied value does not match the port
    call's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.1: "A successful patch bumps the call's `version`."

    Design: Corner/cross_cutting_layers/occ_portcall_patch_stale_version
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    version = pc["version"]
    pc = validate_success(api_client.patch_port_call(
        pc["id"], {"expected_port_call_version": version, "eta": "2026-06-01T12:00:00Z"},
        make_agency_ops_headers()))
    assert pc["version"] == version + 1
    assert pc["eta"] == "2026-06-01T12:00:00Z"
    resp = api_client.patch_port_call(
        pc["id"], {"expected_port_call_version": version, "etd": "2026-06-03T12:00:00Z"},
        make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    pc_now = validate_success(api_client.get_port_call(pc["id"], make_agency_ops_headers()))
    assert pc_now["etd"] == "2026-06-02T10:00:00Z", "etd unchanged by the stale patch"


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_layers / occ_da_create_stale_and_supersede
# ---------------------------------------------------------------------------

def test_occ_da_create_stale_and_supersede(api):
    """PRD §2.8: "A disbursement-account creation request must carry
    `expected_port_call_version` holding the caller's last observed `version`
    of the target port call; because creating an account legitimately
    supersedes any existing pro-forma account of the same call, a writer
    acting on a stale view would otherwise silently replace an account it
    never saw ... if the supplied value does not match the port call's
    current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §3.8: "Exactly one non-`SUPERSEDED` account exists per call: creation
    supersedes any existing `PRO_FORMA` account of the same call, moving it
    to `SUPERSEDED`"; "Creation ... bumps the port call's `version`."

    Design: Corner/cross_cutting_layers/occ_da_create_stale_and_supersede
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    v1 = pc["version"]
    da1 = create_da_for_call(pc)  # bumps port call version v1 -> v1+1
    resp = api_client.create_disbursement_account(
        {"port_call_id": pc["id"], "expected_port_call_version": v1},
        make_agency_ops_headers("ops-2"))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    pc_now = validate_success(api_client.get_port_call(pc["id"], make_agency_ops_headers()))
    da2 = validate_success(api_client.create_disbursement_account(
        {"port_call_id": pc["id"], "expected_port_call_version": pc_now["version"]},
        make_agency_ops_headers("ops-2")), expected_status=201)
    assert da2["status"] == "PRO_FORMA"
    da1_now = validate_success(api_client.get_disbursement_account(da1["id"], make_agency_ops_headers()))
    assert da1_now["status"] == "SUPERSEDED"
    pc_now = validate_success(api_client.get_port_call(pc["id"], make_agency_ops_headers()))
    assert pc_now["version"] == v1 + 2, "each create bumps the port call version by 1"


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_layers / clock_default_is_fixed_epoch
# ---------------------------------------------------------------------------

def test_clock_default_is_fixed_epoch(api):
    """PRD §2.5: "The system never consults wall-clock time. Every notion of
    'now' — filing deadlines, window openings, late-cancellation cutoffs,
    shore-pass expiry, receipt timestamps — is read from a logical clock
    whose startup default, before anyone sets it, is exactly
    `2026-05-01T00:00:00Z`."

    Design: Corner/cross_cutting_layers/clock_default_is_fixed_epoch
    """
    # No clock call issued at all: the default epoch applies.
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"], eta="2026-06-10T20:00:00Z",
                          etd="2026-06-13T01:00:00Z")
    for auth_type in ("PORT_STATE_CONTROL", "IMMIGRATION", "CUSTOMS", "HARBOR_MASTER"):
        n = create_notification(pc["id"], auth_type, payload_summary=auth_type[0].lower())
        get_success_data(api_client.submit_notification(n["id"], make_agency_ops_headers()))
    bw = create_berth_window(pc["id"], berth_code="B22",
                             start_at="2026-06-10T18:00:00Z", end_at="2026-06-14T06:00:00Z")
    get_success_data(api_client.confirm_berth_window(bw["id"], make_port_authority_headers()))
    # Filing for a June ETA succeeds under the default clock (2026-05-01 <= eta-24h)
    pc = validate_success(api_client.file_pre_arrival(pc["id"], make_agency_ops_headers()))
    assert pc["ops_status"] == "PRE_ARRIVAL_FILED"
    # Occupy of the June window fails: the default epoch precedes the window
    resp = api_client.occupy_berth_window(bw["id"], make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_STARTED)


# ---------------------------------------------------------------------------
# Queue B: rbac / ops_cannot_create_principal_forbidden
# ---------------------------------------------------------------------------

def test_ops_cannot_create_principal_forbidden(api):
    """PRD §2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint is rejected with
    `ERR_FORBIDDEN_ROLE`"; PRD §4: `POST /principals` is authorized for
    `AgencyAdmin` only.

    Design: Corner/rbac/ops_cannot_create_principal_forbidden
    """
    resp = api_client.create_principal(
        {"name": "Apex", "contact_email": "a@x.example", "credit_limit_cents": 0},
        make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


# ---------------------------------------------------------------------------
# Queue B: rbac / vendor_rep_cannot_finalize_da
# ---------------------------------------------------------------------------

def test_vendor_rep_cannot_finalize_da(api):
    """PRD §2.7: "2. **Role authorization** — the acting role appears in the
    endpoint's authorized set, including the conditional actor rules such as
    the kind-dependent service-order confirmation described in §3.5;
    otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403)." This stage precedes
    state-machine legality (stage 6), so a forbidden role surfaces
    `ERR_FORBIDDEN_ROLE` even when the account's state would also reject the
    transition. PRD §4 authorizes `POST /disbursement-accounts/{id}/finalize`
    for `AgencyFinance` only.

    Design: Corner/rbac/vendor_rep_cannot_finalize_da
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    da = create_da_for_call(pc)  # PRO_FORMA — state would also reject
    vendor = create_vendor(name="ChandlerCo", categories=["PROVISIONS"],
                           contact_email="c@x.example")
    resp = api_client.finalize_disbursement_account(
        da["id"], make_vendor_rep_headers(vendor["id"]))
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_FORBIDDEN_ROLE", (
        f"role check precedes state check; got {body['data']['error_id']}")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Queue B: rbac / finance_cannot_grant_visa_forbidden
# ---------------------------------------------------------------------------

def test_finance_cannot_grant_visa_forbidden(api):
    """PRD §3.6: "A `PortAuthority` officer then grants the visa"; PRD §2.1:
    "A request whose role is not listed among the roles authorized for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/finance_cannot_grant_visa_forbidden
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    cc = create_crew_change(pc["id"], nationality="IN", requires_visa=True)
    get_success_data(api_client.verify_docs(cc["id"], make_crewing_agent_headers()))
    cc = get_success_data(api_client.request_visa(cc["id"], make_crewing_agent_headers()))
    assert cc["status"] == "VISA_PENDING"
    resp = api_client.grant_visa(cc["id"], {"visa_reference": "V-1"},
                                 make_agency_finance_headers())
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    cc_now = validate_success(api_client.get_crew_change(cc["id"], make_crewing_agent_headers()))
    assert cc_now["status"] == "VISA_PENDING"


# ---------------------------------------------------------------------------
# Queue B: rbac / pilot_confirm_by_vendor_rep_forbidden
# ---------------------------------------------------------------------------

def test_pilot_confirm_by_vendor_rep_forbidden(api):
    """PRD §3.5: "A `PILOT` order is confirmed by a `PortAuthority` officer;
    every other kind is confirmed by the `VendorRep` that owns the order's
    `vendor_id`. The endpoint admits both roles, but confirming through the
    wrong side is rejected with `ERR_CONFIRM_ROLE_MISMATCH`."

    Design: Corner/rbac/pilot_confirm_by_vendor_rep_forbidden
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"], eta="2026-06-04T08:00:00Z",
                          etd="2026-06-05T08:00:00Z")
    vendor = create_vendor(name="TugCo", categories=["STORES"], contact_email="t@x.example")
    so_pilot = create_service_order(
        pc["id"], kind="PILOT", resource_unit="PILOT-BOAT-1",
        window_start="2026-06-04T10:00:00Z", window_end="2026-06-04T11:00:00Z",
        estimated_cents=8000)
    so_tug = create_service_order(
        pc["id"], kind="TUG", vendor_id=vendor["id"], resource_unit="TUG-3",
        window_start="2026-06-04T10:00:00Z", window_end="2026-06-04T11:00:00Z",
        estimated_cents=8000)
    resp1 = api_client.confirm_service_order(so_pilot["id"], make_vendor_rep_headers(vendor["id"]))
    validate_error(resp1, ApiErrorId.ERR_CONFIRM_ROLE_MISMATCH)
    resp2 = api_client.confirm_service_order(so_tug["id"], make_port_authority_headers())
    validate_error(resp2, ApiErrorId.ERR_CONFIRM_ROLE_MISMATCH)
    so_pilot_now = validate_success(api_client.get_service_order(so_pilot["id"], make_agency_ops_headers()))
    so_tug_now = validate_success(api_client.get_service_order(so_tug["id"], make_agency_ops_headers()))
    assert so_pilot_now["status"] == "ORDERED"
    assert so_tug_now["status"] == "ORDERED"


# ---------------------------------------------------------------------------
# Queue B: rbac / principal_rep_cannot_advance_foreign_da
# ---------------------------------------------------------------------------

def test_principal_rep_cannot_advance_foreign_da(api):
    """PRD §3.8: "a `PrincipalRep`, which may fund only accounts belonging to
    its own principal, failing which the attempt is rejected with
    `ERR_NOT_RESOURCE_OWNER`."
    PRD §2.1: "ownership checks on any resource that references a Principal
    compare the resource's `principal_id` to `X-User-ID`, and a mismatch is
    rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/principal_rep_cannot_advance_foreign_da
    """
    pa = create_principal(name="Apex A", credit_limit_cents=0)
    pb = create_principal(name="Borealis B", contact_email="b@x.example", credit_limit_cents=0)
    pc = create_port_call(pa["id"])
    da = create_da_for_call(pc)
    get_success_data(api_client.send_disbursement_account(da["id"], make_agency_ops_headers()))
    resp = api_client.create_funding_advance(
        da["id"], {"amount_cents": 1000}, make_principal_rep_headers(pb["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    advances, _ = validate_paginated(api_client.list_funding_advances(
        make_agency_finance_headers(), params={"da_id": da["id"]}))
    assert len(advances) == 0, "no advance created"


# ---------------------------------------------------------------------------
# Queue B: rbac / missing_auth_headers_unauthenticated
# ---------------------------------------------------------------------------

def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request that arrives without these headers, or whose
    `X-User-Role` is not one of the declared roles, is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api_client.list_port_calls(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
