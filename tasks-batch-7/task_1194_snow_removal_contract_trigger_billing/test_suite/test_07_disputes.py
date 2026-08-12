"""Disputes: evidence cycle, segregation of duties, resolution side effects."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_dispute_payload, setup_active_per_push, setup_storm_event, set_clock,
    setup_billable_visit, setup_issued_event_invoice, schedule_visit, run_visit,
    verify_event_with_two_sources,
    make_client_headers, make_dispatcher_headers, make_crew_headers,
)

DISPATCH = TEST_USERS["ops_dispatcher_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

_OBS = [("NOAA", "2026-12-10T07:30:00Z", 2.0), ("DTN", "2026-12-10T08:00:00Z", 2.1)]


def _setup_disputed_invoice(api, client_name, reason, issuer="disp-1",
                            completer="crew-9"):
    """Issued 45000 EVENT invoice (issued by `issuer`) over one visit completed
    by `completer`, with a client-opened dispute in OPEN. Returns context dict."""
    ctx = setup_active_per_push(client_name=client_name, trigger_depth_inches=1.0)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit = schedule_visit(event["id"], ctx["contract_site"]["id"])
    run_visit(visit["id"], "2026-12-10T09:05:00Z", "2026-12-10T10:00:00Z",
              headers=make_crew_headers(completer))
    verify_event_with_two_sources(event["id"], _OBS)
    invoice = setup_issued_event_invoice(ctx, event, make_dispatcher_headers(issuer))
    dispute = get_success_data(api.create_dispute(
        create_dispute_payload(invoice["id"], visit["id"], reason),
        make_client_headers(ctx["client"]["id"])))
    return {"ctx": ctx, "event": event, "visit": visit, "invoice": invoice,
            "dispute": dispute}


def test_dispute_evidence_cycle_and_upheld_resolution(api):
    """PRD §3.8: "The client submits evidence — an `evidence_note`, a list of `photo_ids` referencing ServicePhoto records, or both, with at least one of the two required, failing as `ERR_EVIDENCE_REQUIRED` — which appends to the dispute's `evidence_items` and moves it from `OPEN` to `EVIDENCE_REVIEW`. A dispatcher who finds the file thin may request more evidence with a `note`, returning the dispute from `EVIDENCE_REVIEW` to `OPEN`, and the cycle may repeat."
    PRD §3.8: "Resolving `UPHELD` moves the dispute to `RESOLVED_UPHELD`, applies a `resolution_credit_cents` of zero, and settles the visit's billing from `DISPUTED` to `SETTLED`."

    Design: Corner/state_machines/dispute_evidence_cycle_and_upheld_resolution
    """
    sc = _setup_disputed_invoice(api, "Cycle Client", "TRIGGER_NOT_MET")
    dispute = sc["dispute"]
    assert dispute["status"] == "OPEN"

    s1 = validate_success(api.submit_dispute_evidence(
        dispute["id"], {"evidence_note": "Our gauge read 0.8 in"},
        make_client_headers(sc["ctx"]["client"]["id"])), 200)
    assert s1["status"] == "EVIDENCE_REVIEW"

    s2 = validate_success(api.request_dispute_evidence(
        dispute["id"], {"note": "Need dated photos"}, DISPATCH), 200)
    assert s2["status"] == "OPEN"

    s3 = validate_success(api.submit_dispute_evidence(
        dispute["id"],
        {"evidence_note": "Photos attached separately; stand by gauge"},
        make_client_headers(sc["ctx"]["client"]["id"])), 200)
    assert s3["status"] == "EVIDENCE_REVIEW"

    # Resolver disp-2 differs from issuer disp-1 and completer crew-9.
    resolved = validate_success(api.resolve_dispute(
        dispute["id"], {"outcome": "UPHELD"}, make_dispatcher_headers("disp-2")), 200)
    assert resolved["status"] == "RESOLVED_UPHELD"
    assert resolved["resolution_credit_cents"] == 0

    invoice_after = validate_success(api.get_invoice(sc["invoice"]["id"], DISPATCH), 200)
    assert invoice_after["total_cents"] == 45_000
    assert invoice_after["credit_cents"] == 0

    visit_after = validate_success(api.get_visit(sc["visit"]["id"], DISPATCH), 200)
    assert visit_after["billing_status"] == "SETTLED"


def test_dispute_submit_evidence_requires_content(api):
    """PRD §3.8: "The client submits evidence — an `evidence_note`, a list of `photo_ids` referencing ServicePhoto records, or both, with at least one of the two required, failing as `ERR_EVIDENCE_REQUIRED`"

    Design: Corner/validations/dispute_submit_evidence_requires_content
    """
    sc = _setup_disputed_invoice(api, "Evidence Co", "RATE_DISAGREEMENT")
    validate_error(api.submit_dispute_evidence(
        sc["dispute"]["id"], {}, make_client_headers(sc["ctx"]["client"]["id"])),
        ApiErrorId.ERR_EVIDENCE_REQUIRED)

    after = validate_success(api.get_dispute(sc["dispute"]["id"], DISPATCH), 200)
    assert after["status"] == "OPEN"


def test_dispute_visit_not_on_invoice_returns_line_not_found(api):
    """PRD §3.8: "The visit must appear among the invoice's lines, failing as `ERR_DISPUTE_LINE_NOT_FOUND`"

    Design: Corner/validations/dispute_visit_not_on_invoice_returns_line_not_found
    """
    ctx = setup_active_per_push(client_name="Line Co", trigger_depth_inches=1.0,
                                completion_target_minutes=480)
    set_clock("2026-12-10T07:00:00Z")
    e1 = setup_storm_event()
    setup_billable_visit(ctx, e1, _OBS)
    e2 = setup_storm_event(window_start="2026-12-12T00:00:00Z",
                           window_end="2026-12-12T06:00:00Z")
    v_b, _ = setup_billable_visit(
        ctx, e2,
        [("NOAA", "2026-12-12T05:00:00Z", 2.0), ("DTN", "2026-12-12T05:30:00Z", 2.1)],
        scheduled_start="2026-12-12T09:00:00Z",
        scheduled_end="2026-12-12T10:00:00Z",
        start_at="2026-12-12T09:05:00Z", complete_at="2026-12-12T10:00:00Z")

    invoice = setup_issued_event_invoice(ctx, e1)  # covers ONLY event e1
    validate_error(api.create_dispute(
        create_dispute_payload(invoice["id"], v_b["id"], "INCOMPLETE_SERVICE"),
        make_client_headers(ctx["client"]["id"])),
        ApiErrorId.ERR_DISPUTE_LINE_NOT_FOUND)


def test_dispute_resolver_segregated_from_issuer(api):
    """PRD §3.8: "Resolution is dispatcher work with a hard segregation-of-duties gate: the resolver's `X-User-ID` must differ from the invoice's `issued_by_user_id` and from the visit's `completed_by_user_id`, failing as `ERR_DISPUTE_SEGREGATION`."

    Design: Corner/roles/dispute_resolver_segregated_from_issuer
    """
    sc = _setup_disputed_invoice(api, "Seg Co", "MATERIAL_QUANTITY")
    dispute = sc["dispute"]
    get_success_data(api.submit_dispute_evidence(
        dispute["id"], {"evidence_note": "Scale tickets differ"},
        make_client_headers(sc["ctx"]["client"]["id"])))

    # The issuer (disp-1) cannot resolve.
    validate_error(api.resolve_dispute(dispute["id"], {"outcome": "UPHELD"},
                                       make_dispatcher_headers("disp-1")),
                   ApiErrorId.ERR_DISPUTE_SEGREGATION)
    # Nor can a dispatcher identity carrying the completer's id (crew-9).
    validate_error(api.resolve_dispute(dispute["id"], {"outcome": "UPHELD"},
                                       make_dispatcher_headers("crew-9")),
                   ApiErrorId.ERR_DISPUTE_SEGREGATION)

    resolved = validate_success(api.resolve_dispute(
        dispute["id"], {"outcome": "UPHELD"}, make_dispatcher_headers("disp-2")), 200)
    assert resolved["status"] == "RESOLVED_UPHELD"
