"""Error-path behaviour: authentication, ownership, identifier resolution, and
the refusals that guard quoting, binding, and the proof-review loop.

Every test builds the state it needs through the public API only.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ErrorId
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.assertions import assert_money, assert_total_count, data_of
from test_helpers.test_users import (
    ADJUSTER_HEADERS,
    PANEL_ADMIN_HEADERS,
    UNDERWRITER_2_HEADERS,
    UNDERWRITER_HEADERS,
    make_insured_headers,
)

# A syntactically valid UUID that no row in the system ever carries.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"


def test_application_read_with_missing_user_headers_is_unauthenticated(api):
    """A read with neither identity header set is refused before the body matters.

    "Both must be present and non-empty; a missing or blank header is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401) before the request body is parsed at
    all."

    "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/errors/application_read_with_missing_x_user_headers_returns_401
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    FX.seed_catalog(api)
    account = FX.create_account(api)
    application = FX.create_application(api, account["id"])

    response = api.raw_get(f"/applications/{application['id']}")

    validate_error(response, ErrorId.UNAUTHENTICATED)
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_")
    assert isinstance(meta.get("api_request_timestamp"), str)
    assert meta["api_request_timestamp"]

    # The same read with a proper identity still works, so the row itself is fine.
    readable = data_of(api.get_application(application["id"], UNDERWRITER_HEADERS))
    assert readable["id"] == application["id"]


def test_application_read_by_a_foreign_insured_is_an_account_scope_violation(api):
    """An existing row belonging to another account answers 403, not 404.

    "A read or write by an `Insured` against a row belonging to another account
    is rejected with `ERR_ACCOUNT_SCOPE_VIOLATION` (HTTP 403). Ownership is
    evaluated **after** existence, so a foreign row that does exist yields 403,
    not 404."

    Design: Corner/errors/application_read_by_a_foreign_insured_returns_403
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    FX.seed_catalog(api)
    owner_account = FX.create_account(api, C.ACCOUNT_AURORA)
    other_account = FX.create_account(api, C.ACCOUNT_BITWISE)
    application = FX.create_application(api, owner_account["id"])

    foreign = api.get_application(
        application["id"], make_insured_headers(other_account["id"])
    )
    validate_error(foreign, ErrorId.ACCOUNT_SCOPE_VIOLATION)

    # The owning account reads exactly the same row without trouble.
    mine = data_of(
        api.get_application(application["id"], make_insured_headers(owner_account["id"]))
    )
    assert mine["id"] == application["id"]
    assert mine["insured_account_id"] == owner_account["id"]


def test_unknown_scan_engagement_and_proof_ids_report_their_own_not_found(api):
    """Each dangling path identifier names the 404 belonging to its own type.

    "The request fails on the *first* identifier that does not resolve, with the
    404 error belonging to that identifier's type: `insured_account_id` yields
    `ERR_INSURED_ACCOUNT_NOT_FOUND`, `application_id` yields
    `ERR_APPLICATION_NOT_FOUND`, `scan_id` yields
    `ERR_EXTERNAL_SCAN_NOT_FOUND`, `policy_id` yields `ERR_POLICY_NOT_FOUND`,
    `section_id` yields `ERR_COVERAGE_SECTION_NOT_FOUND`, `claim_id` yields
    `ERR_INCIDENT_CLAIM_NOT_FOUND`, `engagement_id` yields
    `ERR_VENDOR_ENGAGEMENT_NOT_FOUND`, `proof_id` yields
    `ERR_PROOF_OF_LOSS_NOT_FOUND`, `payment_id` yields
    `ERR_CLAIM_PAYMENT_NOT_FOUND`, `assessment_id` yields
    `ERR_RENEWAL_ASSESSMENT_NOT_FOUND`, `scenario_id` yields
    `ERR_SYSTEMIC_SCENARIO_NOT_FOUND`, and `vendor_id` yields
    `ERR_PANEL_VENDOR_NOT_FOUND`."

    Design: Corner/errors/unknown_scan_engagement_and_proof_ids_return_not_found
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    chain = FX.bound_policy(api)
    assert chain["policy"]["id"]

    validate_error(
        api.get_external_scan(MISSING_UUID, UNDERWRITER_HEADERS),
        ErrorId.EXTERNAL_SCAN_NOT_FOUND,
    )
    validate_error(
        api.get_vendor_engagement(MISSING_UUID, UNDERWRITER_HEADERS),
        ErrorId.VENDOR_ENGAGEMENT_NOT_FOUND,
    )
    validate_error(
        api.get_proof_of_loss(MISSING_UUID, UNDERWRITER_HEADERS),
        ErrorId.PROOF_OF_LOSS_NOT_FOUND,
    )

    # The scan that does exist reads normally, so the identifier is what failed.
    existing = data_of(api.get_external_scan(chain["scan"]["id"], UNDERWRITER_HEADERS))
    assert existing["id"] == chain["scan"]["id"]


def test_unknown_payment_assessment_and_claim_ids_report_their_own_not_found(api):
    """Payment, assessment, and claim identifiers each carry their own 404.

    "The request fails on the *first* identifier that does not resolve, with the
    404 error belonging to that identifier's type: `insured_account_id` yields
    `ERR_INSURED_ACCOUNT_NOT_FOUND`, `application_id` yields
    `ERR_APPLICATION_NOT_FOUND`, `scan_id` yields
    `ERR_EXTERNAL_SCAN_NOT_FOUND`, `policy_id` yields `ERR_POLICY_NOT_FOUND`,
    `section_id` yields `ERR_COVERAGE_SECTION_NOT_FOUND`, `claim_id` yields
    `ERR_INCIDENT_CLAIM_NOT_FOUND`, `engagement_id` yields
    `ERR_VENDOR_ENGAGEMENT_NOT_FOUND`, `proof_id` yields
    `ERR_PROOF_OF_LOSS_NOT_FOUND`, `payment_id` yields
    `ERR_CLAIM_PAYMENT_NOT_FOUND`, `assessment_id` yields
    `ERR_RENEWAL_ASSESSMENT_NOT_FOUND`, `scenario_id` yields
    `ERR_SYSTEMIC_SCENARIO_NOT_FOUND`, and `vendor_id` yields
    `ERR_PANEL_VENDOR_NOT_FOUND`."

    Design: Corner/errors/unknown_payment_assessment_and_claim_ids_return_not_found
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    chain = FX.bound_policy(api)
    assert chain["policy"]["id"]

    validate_error(
        api.get_claim_payment(MISSING_UUID, ADJUSTER_HEADERS),
        ErrorId.CLAIM_PAYMENT_NOT_FOUND,
    )
    validate_error(
        api.get_renewal_assessment(MISSING_UUID, UNDERWRITER_HEADERS),
        ErrorId.RENEWAL_ASSESSMENT_NOT_FOUND,
    )
    validate_error(
        api.get_incident_claim(MISSING_UUID, ADJUSTER_HEADERS),
        ErrorId.INCIDENT_CLAIM_NOT_FOUND,
    )

    # No payment row was conjured by any of those reads.
    assert_total_count(api.list_claim_payments(ADJUSTER_HEADERS), 0)


def test_unknown_panel_vendor_id_reports_not_found_from_path_and_from_body(api):
    """A dangling panel firm is a 404 whether it arrives in the path or the body.

    "The request fails on the *first* identifier that does not resolve, with the
    404 error belonging to that identifier's type" and "`vendor_id` yields
    `ERR_PANEL_VENDOR_NOT_FOUND`."

    "An `insured_account_id` naming no account, an `application_id` naming no
    application, a `policy_id` naming no policy, a `systemic_event_scenario_id`
    naming no scenario, and a directed `panel_vendor_id` naming no panel firm
    each yield the corresponding 404."

    Design: Corner/errors/unknown_panel_vendor_id_returns_not_found_from_path_and_body
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    chain = FX.bound_policy(api)
    FX.set_clock(api, "2026-09-10T00:00:00Z")
    claim = FX.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )

    # The identifier in the path.
    validate_error(
        api.update_panel_vendor(
            MISSING_UUID, {"status": "SUSPENDED"}, PANEL_ADMIN_HEADERS
        ),
        ErrorId.PANEL_VENDOR_NOT_FOUND,
    )

    # The same identifier directed through a request body.
    payload = F.vendor_engagement_payload(
        vendor_type="NOTIFICATION",
        deployment_start_at="2026-09-11T00:00:00Z",
        deployment_end_at="2026-09-21T00:00:00Z",
        authorized_hours_cap=40,
    )
    payload["panel_vendor_id"] = MISSING_UUID
    validate_error(
        api.create_vendor_engagement(claim["id"], payload, ADJUSTER_HEADERS),
        ErrorId.PANEL_VENDOR_NOT_FOUND,
    )

    # No engagement was created against the claim.
    assert_total_count(
        api.list_vendor_engagements(
            ADJUSTER_HEADERS, params={"incident_claim_id": claim["id"]}
        ),
        0,
    )
    unchanged = FX.read_claim(api, claim["id"])
    assert unchanged["status"] == "COVERAGE_CONFIRMED"


def test_confirming_a_section_absent_from_the_tower_is_not_found(api):
    """A covered key the bound tower never contained refuses the confirmation.

    "A `covered_section_keys` entry naming a `section_key` that the claim's
    policy tower does not contain yields `ERR_COVERAGE_SECTION_NOT_FOUND`."

    "On success `covered_section_keys` and `reservation_of_rights` are stored,
    `reserved_amount_usd` is set from `initial_reserve_usd`, and the claim's
    `version` is incremented by 1."

    Design: Corner/errors/confirming_a_section_absent_from_the_tower_returns_not_found
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    chain = FX.bound_policy(
        api,
        account_spec=C.ACCOUNT_BITWISE,
        requested_aggregate_limit_usd=250000,
        requested_retention_usd=0,
        coverage_sections=C.SMALL_TOWER,
    )
    assert sorted(chain["sections"]) == ["BUSINESS_INTERRUPTION", "FIRST_PARTY_RESPONSE"]

    FX.set_clock(api, "2026-09-10T00:00:00Z")
    claim = FX.notify_claim(
        api,
        chain["policy"]["id"],
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
    )
    FX.triage_claim(api, claim["id"])
    triaged = FX.read_claim(api, claim["id"])

    refused = api.confirm_coverage(
        claim["id"],
        F.confirm_coverage_payload(
            covered_section_keys=["FIRST_PARTY_RESPONSE", "CYBER_EXTORTION"],
            initial_reserve_usd=100000,
        ),
        ADJUSTER_HEADERS,
    )
    validate_error(refused, ErrorId.COVERAGE_SECTION_NOT_FOUND)

    after = FX.read_claim(api, claim["id"])
    assert after["status"] == "TRIAGE"
    assert after["version"] == triaged["version"]
    assert_money(after["reserved_amount_usd"], 0, "reserved_amount_usd")

    # The subset that the tower does contain is accepted.
    confirmed = FX.confirm_coverage(
        api,
        claim["id"],
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=100000,
    )
    assert confirmed["status"] == "COVERAGE_CONFIRMED"
    assert_money(confirmed["reserved_amount_usd"], 100000, "reserved_amount_usd")


def test_quote_after_a_new_mandatory_control_is_catalogued_is_refused(api):
    """The mandatory gap is recomputed against the catalog as it stands at quote time.

    "The verified-basis mandatory gap is **recomputed at quote time** against
    the control catalog exactly as it stands in that request, and the recomputed
    count must be zero. This is stricter than reading the stored
    `mandatory_gap_count`: a mandatory control added to the catalog after the
    scan completed has no attestation and no observed level, so it opens a gap
    and blocks the quote even though the stored count still reads 0. Failure is
    `ERR_MANDATORY_CONTROL_GAP`."

    "Permanence has a consequence worth stating plainly: because the posture
    score's denominator is the sum of *every* catalog weight, adding a control
    changes the denominator of every score computed from that moment on, and
    adding a mandatory control can open a gap on an application that had none."

    Design: Corner/errors/quote_after_a_new_mandatory_control_is_catalogued_returns_422
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    catalog_rows = [
        row
        for row in C.STANDARD_CATALOG
        if row["control_key"] != "INCIDENT_RESPONSE_PLAN"
    ]
    FX.seed_catalog(api, catalog_rows)
    account = FX.create_account(api)
    application = FX.create_application(api, account["id"])
    FX.attest_controls(
        api,
        application["id"],
        {
            "MFA_PRIVILEGED": "FULL",
            "OFFLINE_BACKUPS": "FULL",
            "EDR_COVERAGE": "FULL",
            "EMAIL_FILTERING": "FULL",
        },
    )
    FX.submit_application(api, application["id"])
    scan = FX.order_scan(api, application["id"])
    FX.complete_scan(
        api, scan["id"], [F.scan_finding("EMAIL_FILTERING", "HIGH", "PARTIAL")]
    )

    before = FX.read_application(api, application["id"])
    assert before["status"] == "UNDERWRITING"
    assert before["mandatory_gap_count"] == 0

    # A mandatory control is catalogued after the scan completed.
    data_of(
        api.create_control_requirement(
            F.control_requirement_payload(
                control_key="INCIDENT_RESPONSE_PLAN",
                min_level_required="PARTIAL",
                weight=10,
                is_mandatory=True,
            ),
            UNDERWRITER_HEADERS,
        ),
        201,
    )

    current = FX.read_application(api, application["id"])
    refused = api.quote_application(
        application["id"],
        F.quote_payload(current["version"]),
        UNDERWRITER_HEADERS,
    )
    validate_error(refused, ErrorId.MANDATORY_CONTROL_GAP)

    after = FX.read_application(api, application["id"])
    assert after["status"] == "UNDERWRITING"
    # The stored counter still reads 0 even though the quote was blocked.
    assert after["mandatory_gap_count"] == 0
    assert after["version"] == current["version"]


def test_bind_exactly_at_the_quote_expiry_instant_is_refused(api):
    """Binding at the expiry instant itself is refused, not merely after it.

    "Two further gates apply: the current clock instant must be strictly before
    `quote_expires_at`, since binding at or after that instant is refused with
    `ERR_QUOTE_EXPIRED`; and `mandatory_gap_count` must be zero."

    "On success the bindable pricing run writes `premium_usd`,
    `quoted_by_user_id` is stamped with the acting `X-User-ID`,
    `quote_expires_at` is set to the current logical clock instant plus 30 days,
    and the application's `version` is incremented by 1."

    Design: Corner/errors/bind_exactly_at_the_quote_expiry_instant_returns_422
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    chain = FX.quoted_application(api)
    application_id = chain["application"]["id"]
    quoted = FX.read_application(api, application_id)
    assert quoted["status"] == "QUOTED"

    # The quote was issued at 2026-08-01T00:00:00Z, so it expires 30 days later.
    FX.set_clock(api, "2026-08-31T00:00:00Z")

    refused = api.bind_application(
        application_id,
        F.bind_payload(
            quoted["version"],
            period_start="2026-09-01T00:00:00Z",
            period_end="2027-09-01T00:00:00Z",
        ),
        UNDERWRITER_2_HEADERS,
    )
    validate_error(refused, ErrorId.QUOTE_EXPIRED)

    assert_total_count(
        api.list_policies(UNDERWRITER_HEADERS, params={"application_id": application_id}),
        0,
    )
    after = FX.read_application(api, application_id)
    assert after["status"] == "QUOTED"
    assert after["version"] == quoted["version"]


def test_request_info_on_a_superseded_proof_is_refused(api):
    """An amended filing supersedes the earlier proof, which then admits no round.

    "The proof is created in `UNDER_REVIEW`, and any earlier proof of the same
    claim sitting in `UNDER_REVIEW` or `INFO_REQUESTED` is moved to
    `SUPERSEDED` with its `version` incremented by 1 — a claim never has two
    live proofs."

    "The proof must be in `UNDER_REVIEW` — a proof in any other state is refused
    with `ERR_INVALID_PROOF_STATE` — and the claim must be in `PROOF_REVIEW`."

    Design: Corner/errors/request_info_on_a_superseded_proof_returns_409
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    chain = FX.bound_policy(api)
    FX.set_clock(api, "2026-09-10T00:00:00Z")
    claim = FX.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )

    first_proof = FX.file_proof(api, claim["id"], claimed_bi_loss_usd=250000)
    FX.request_info(api, first_proof["id"])
    second_proof = FX.file_proof(api, claim["id"], claimed_bi_loss_usd=260000)

    superseded = data_of(api.get_proof_of_loss(first_proof["id"], ADJUSTER_HEADERS))
    assert superseded["status"] == "SUPERSEDED"

    refused = api.request_proof_info(
        first_proof["id"],
        F.request_info_payload("One more look at the superseded filing."),
        ADJUSTER_HEADERS,
    )
    validate_error(refused, ErrorId.INVALID_PROOF_STATE)

    still_superseded = data_of(
        api.get_proof_of_loss(first_proof["id"], ADJUSTER_HEADERS)
    )
    assert still_superseded["status"] == "SUPERSEDED"
    assert still_superseded["version"] == superseded["version"]

    live = data_of(api.get_proof_of_loss(second_proof["id"], ADJUSTER_HEADERS))
    assert live["status"] == "UNDER_REVIEW"

    claim_after = FX.read_claim(api, claim["id"])
    assert claim_after["status"] == "PROOF_REVIEW"
    assert claim_after["proof_review_round"] == 1

    # The live proof still accepts a round, so it was the state that mattered.
    granted = validate_success(
        api.request_proof_info(
            second_proof["id"],
            F.request_info_payload("Please supply the ledger extract."),
            ADJUSTER_HEADERS,
        )
    )
    assert granted is not None
