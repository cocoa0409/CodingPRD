"""Composite setup helpers.

Each helper builds its preconditions from scratch (the server DB is empty before
every test) using only PRD-declared endpoints, threading entity_backed identities
(Landlord/Leaseholder/Applicant) with the actual entity ids on every ownership-gated
call. Setup uses get_success_data() so failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data
from .factories import (
    create_landlord_payload, create_leaseholder_payload, create_applicant_payload,
    create_lease_payload, create_listing_payload, create_application_payload,
    create_screening_report_payload, create_agreement_payload,
    create_signature_payload,
)
from .test_users import (
    TEST_USERS, make_landlord_headers, make_leaseholder_headers, make_applicant_headers,
)

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


# --- Primitive builders ---------------------------------------------------

def set_clock(api, iso=DEFAULT_CLOCK):
    return get_success_data(api.set_clock(iso, TEST_USERS["admin_headers"]))


def new_landlord(api, **overrides):
    return get_success_data(api.create_landlord(create_landlord_payload(**overrides), TEST_USERS["admin_headers"]))


def new_leaseholder(api, **overrides):
    return get_success_data(api.create_leaseholder(create_leaseholder_payload(**overrides), TEST_USERS["admin_headers"]))


def new_applicant(api, **overrides):
    return get_success_data(api.create_applicant(create_applicant_payload(**overrides), TEST_USERS["admin_headers"]))


def new_lease(api, landlord, leaseholder, **overrides):
    """Create a lease owned by `landlord` (identity threaded)."""
    payload = create_lease_payload(landlord["id"], leaseholder["id"], **overrides)
    return get_success_data(api.create_lease(payload, make_landlord_headers(landlord["id"])))


def new_verified_lease(api, landlord, leaseholder, **overrides):
    """Create -> submit-verification -> verify(VERIFIED). Returns the verified lease."""
    lease = new_lease(api, landlord, leaseholder, **overrides)
    ll_headers = make_landlord_headers(landlord["id"])
    get_success_data(api.submit_lease_verification(lease["id"], ll_headers))
    return get_success_data(api.verify_lease(lease["id"], {"decision": "VERIFIED"}, TEST_USERS["compliance_headers"]))


def new_draft_listing(api, lease, leaseholder, **overrides):
    payload = create_listing_payload(lease["id"], **overrides)
    return get_success_data(api.create_listing(payload, make_leaseholder_headers(leaseholder["id"])))


def new_open_listing(api, lease, leaseholder, landlord, **overrides):
    """DRAFT listing -> request-approval -> approve. Returns the OPEN listing."""
    listing = new_draft_listing(api, lease, leaseholder, **overrides)
    lh_headers = make_leaseholder_headers(leaseholder["id"])
    get_success_data(api.request_listing_approval(listing["id"], lh_headers))
    return get_success_data(api.approve_listing(listing["id"], make_landlord_headers(landlord["id"])))


def current_listing_version(api, listing_id):
    listing = get_success_data(api.get_listing(listing_id, TEST_USERS["admin_headers"]))
    return listing["version"]


def new_application(api, listing, applicant, **overrides):
    payload = create_application_payload(listing["id"], applicant["id"], **overrides)
    return get_success_data(api.create_application(payload, make_applicant_headers(applicant["id"])))


def screen_application(api, application, credit_score=720, income_verified=True):
    """start-screening -> screening-report. Returns (application_screened, screening_report)."""
    get_success_data(api.start_screening(application["id"], TEST_USERS["compliance_headers"]))
    report = get_success_data(api.create_screening_report(
        application["id"],
        create_screening_report_payload(credit_score=credit_score, income_verified=income_verified),
        TEST_USERS["compliance_headers"],
    ))
    return report


def match_application(api, application):
    return get_success_data(api.match_application(application["id"], TEST_USERS["compliance_headers"]))


def new_matched_application(api, listing, applicant, credit_score=720, income_verified=True, **app_overrides):
    """Application through SUBMITTED -> SCREENING -> SCREENED -> MATCHED. Returns application."""
    application = new_application(api, listing, applicant, **app_overrides)
    screen_application(api, application, credit_score=credit_score, income_verified=income_verified)
    return match_application(api, application)


def get_settlement_for_agreement(api, agreement_id):
    data, _meta = _list(api.list_settlements(TEST_USERS["admin_headers"], params={"agreement_id": agreement_id}))
    return data[0]


def _list(response):
    body = response.json()
    return body["data"], body["meta"]


def draft_agreement(api, listing, application, leaseholder, expected_version=None, **overrides):
    """Draft an agreement for a matched application. Returns (agreement, settlement)."""
    if expected_version is None:
        expected_version = current_listing_version(api, listing["id"])
    payload = create_agreement_payload(application["id"], expected_version, **overrides)
    agreement = get_success_data(api.create_agreement(payload, make_leaseholder_headers(leaseholder["id"])))
    settlement = get_settlement_for_agreement(api, agreement["id"])
    return agreement, settlement


def collect_signatures(api, agreement, landlord, leaseholder, applicant):
    """send-for-signature + all three signatures. Drives agreement to EXECUTED."""
    lh_headers = make_leaseholder_headers(leaseholder["id"])
    get_success_data(api.send_for_signature(agreement["id"], lh_headers))
    get_success_data(api.create_signature(agreement["id"], create_signature_payload("LANDLORD"),
                                           make_landlord_headers(landlord["id"])))
    get_success_data(api.create_signature(agreement["id"], create_signature_payload("LEASEHOLDER"), lh_headers))
    return get_success_data(api.create_signature(agreement["id"], create_signature_payload("APPLICANT"),
                                                  make_applicant_headers(applicant["id"])))


def fund_settlement(api, settlement, applicant, amount=None):
    """Fund with the exact total_move_in_cents unless an amount is supplied."""
    if amount is None:
        amount = settlement["total_move_in_cents"]
    return get_success_data(api.fund_settlement(settlement["id"], {"funded_amount_cents": amount},
                                                 make_applicant_headers(applicant["id"])))


# --- Orchestrator ---------------------------------------------------------

STAGES = ["listing_open", "matched", "drafted", "executed", "funded", "active", "handed_off"]


def setup_scenario(api, stage="active", clock=DEFAULT_CLOCK,
                   lease_overrides=None, listing_overrides=None, applicant_overrides=None,
                   application_overrides=None, agreement_overrides=None,
                   funded_amount=None, handoff_date="2026-06-15"):
    """Build a full sublet/takeover scenario up to `stage`.

    Returns a dict with keys: landlord, leaseholder, applicant, lease, listing,
    application, agreement, settlement (populated up to the requested stage).
    Identities are threaded with real entity ids throughout.
    """
    assert stage in STAGES, f"unknown stage {stage}"
    lease_overrides = lease_overrides or {}
    listing_overrides = listing_overrides or {}
    applicant_overrides = applicant_overrides or {}
    application_overrides = application_overrides or {}
    agreement_overrides = agreement_overrides or {}

    set_clock(api, clock)
    landlord = new_landlord(api)
    leaseholder = new_leaseholder(api)
    applicant = new_applicant(api, **applicant_overrides)
    lease = new_verified_lease(api, landlord, leaseholder, **lease_overrides)
    listing = new_open_listing(api, lease, leaseholder, landlord, **listing_overrides)

    ctx = {
        "landlord": landlord, "leaseholder": leaseholder, "applicant": applicant,
        "lease": lease, "listing": listing,
        "application": None, "agreement": None, "settlement": None,
    }
    if stage == "listing_open":
        return ctx

    application = new_matched_application(api, listing, applicant, **application_overrides)
    ctx["application"] = application
    if stage == "matched":
        return ctx

    agreement, settlement = draft_agreement(api, listing, application, leaseholder, **agreement_overrides)
    ctx["agreement"] = agreement
    ctx["settlement"] = settlement
    if stage == "drafted":
        return ctx

    collect_signatures(api, agreement, landlord, leaseholder, applicant)
    ctx["agreement"] = get_success_data(api.get_agreement(agreement["id"], TEST_USERS["admin_headers"]))
    if stage == "executed":
        return ctx

    fund_settlement(api, settlement, applicant, amount=funded_amount)
    ctx["settlement"] = get_success_data(api.get_settlement(settlement["id"], TEST_USERS["admin_headers"]))
    if stage == "funded":
        return ctx

    get_success_data(api.activate_agreement(agreement["id"], make_leaseholder_headers(leaseholder["id"])))
    ctx["agreement"] = get_success_data(api.get_agreement(agreement["id"], TEST_USERS["admin_headers"]))
    if stage == "active":
        return ctx

    get_success_data(api.handoff_settlement(settlement["id"], {"handoff_date": handoff_date},
                                            make_leaseholder_headers(leaseholder["id"])))
    ctx["settlement"] = get_success_data(api.get_settlement(settlement["id"], TEST_USERS["admin_headers"]))
    return ctx


def setup_dispute_under_review(api, raised_by="APPLICANT", reason="dispute", **scenario_kwargs):
    """ACTIVE agreement -> file dispute -> review. Returns (ctx, dispute)."""
    ctx = setup_scenario(api, stage="active", **scenario_kwargs)
    filer = ctx["applicant"] if raised_by == "APPLICANT" else ctx["leaseholder"]
    if raised_by == "APPLICANT":
        filer_headers = make_applicant_headers(filer["id"])
    else:
        filer_headers = make_leaseholder_headers(filer["id"])
    dispute = get_success_data(api.create_dispute(
        {"agreement_id": ctx["agreement"]["id"], "raised_by": raised_by, "reason": reason}, filer_headers))
    dispute = get_success_data(api.review_dispute(dispute["id"], TEST_USERS["compliance_headers"]))
    return ctx, dispute
