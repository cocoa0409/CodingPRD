"""Agreement creation defaults, initial states, lifecycle, expiry, and OCC
(PRD sections 2.6, 2.7, 3.2, 3.3)."""
from test_helpers import (
    AGREEMENT_DEFAULTS,
    ApiErrorId,
    create_active_agreement,
    create_agreement_payload,
    create_draft_agreement,
    create_licensee,
    create_milestone,
    create_royalty_report_payload,
    create_sublicense_grant_payload,
    make_licensee_headers,
    make_report_line,
    set_clock,
    submit_report,
    suspend_agreement,
    validate_error,
    validate_success,
)


def test_agreement_defaults_applied(api, analyst_headers):
    """PRD section 3.2: "`minimum_period_royalty_cents` establishes a
    per-report royalty floor; it defaults to 0, which means no minimum.
    Sublicensing is configured by `sublicense_allowed` (default false) and
    `sublicense_passthrough_rate_bp` (default 0) ... The most-favored-licensee
    configuration comprises `mfl_clause` (default false), `mfl_mode`
    (`RETROACTIVE` or `PROSPECTIVE`, default `RETROACTIVE`), and
    `mfl_lookback_quarters` (default 4, at least 1). Audit reach is set by
    `audit_window_months` (default 24, at least 1), and screening sensitivity
    by `underreport_tolerance_bp` (default 500)." and "A new agreement starts
    in `DRAFT`."

    Design: Corner/entities/agreement_defaults_applied
    """
    licensee = create_licensee(legal_name="Def Co")
    resp = api.create_agreement(
        create_agreement_payload(licensee["id"], patent_reference="US-12121-T1"),
        analyst_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["minimum_period_royalty_cents"] == 0
    assert data["sublicense_allowed"] is False
    assert data["sublicense_passthrough_rate_bp"] == 0
    assert data["mfl_clause"] is False
    assert data["mfl_mode"] == "RETROACTIVE"
    assert data["mfl_lookback_quarters"] == 4
    assert data["audit_window_months"] == 24
    assert data["underreport_tolerance_bp"] == 500
    assert data["status"] == "DRAFT"
    assert data["cumulative_accepted_base_cents"] == 0
    assert data["undistributed_pool_cents"] == 0
    assert data["mfl_adjusted_rate_bp"] is None


def test_initial_states_on_creation(api, analyst_headers):
    """PRD section 3.1: "A new licensee starts in `ACTIVE` status". PRD
    section 3.2: "A new agreement starts in `DRAFT`." PRD section 3.4: "A new
    milestone starts `PENDING`, with `achieved_at` null." PRD section 3.5: "A
    new grant starts `PENDING`." PRD section 3.6: "The report is born in
    `SUBMITTED` status." PRD section 3.7: "The audit itself starts in
    `INITIATED`".

    Design: Corner/state_machines/initial_states_on_creation
    """
    licensee = create_licensee(legal_name="Init Co")
    assert licensee["status"] == "ACTIVE"

    agreement = create_draft_agreement(
        licensee, patent_reference="US-23232-U1", sublicense_allowed=True
    )
    assert agreement["status"] == "DRAFT"

    milestone = create_milestone(agreement["id"], name="M", threshold_cents=1_000_000,
                                 fee_cents=100)
    assert milestone["status"] == "PENDING"
    assert milestone["achieved_at"] is None

    agreement = validate_success(
        api.agreement_lifecycle(agreement["id"], {"action": "ACTIVATE"}, analyst_headers)
    )

    resp = api.create_sublicense_grant(
        create_sublicense_grant_payload(agreement["id"]),
        make_licensee_headers(licensee["id"]),
    )
    grant = validate_success(resp, expected_status=201)
    assert grant["status"] == "PENDING"

    report = submit_report(agreement, licensee)
    assert report["status"] == "SUBMITTED"

    audit = validate_success(
        api.create_audit(
            {"agreement_id": agreement["id"],
             "scope_period_start": "2026-03-01T00:00:00Z",
             "scope_period_end": "2026-03-31T00:00:00Z"},
        analyst_headers,
    ),
        expected_status=201,
    )
    assert audit["status"] == "INITIATED"


def test_agreement_auto_expire_on_clock(api, analyst_headers, ipadmin_headers):
    """PRD section 2.6: "every agreement in `ACTIVE` or `SUSPENDED` status
    whose `expiration_date` is strictly earlier than the new logical time
    transitions to `EXPIRED`, with the usual version increment." PRD section
    3.2: "Royalty report submission and sublicense requests require the
    agreement `ACTIVE`. ... Any of these operations attempted against an
    agreement outside its permitted status set is rejected with
    `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/state_machines/agreement_auto_expire_on_clock
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-89898-A2",
        expiration_date="2026-09-01T00:00:00Z",
    )
    set_clock("2026-10-01T00:00:00Z")

    resp = api.get_agreement(agreement["id"], analyst_headers)
    data = validate_success(resp)
    assert data["status"] == "EXPIRED"

    payload = create_royalty_report_payload(
        agreement["id"], licensee["id"], lines=[make_report_line(gross_sales_cents=1000)]
    )
    err = api.create_royalty_report(payload, make_licensee_headers(licensee["id"]))
    validate_error(err, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_report_requires_active_agreement_suspended(api, analyst_headers):
    """PRD section 3.2: "Royalty report submission and sublicense requests
    require the agreement `ACTIVE`. ... Any of these operations attempted
    against an agreement outside its permitted status set is rejected with
    `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/report_requires_active_agreement
    """
    licensee, agreement = create_active_agreement(patent_reference="US-44444-M1")
    suspend_agreement(agreement["id"])

    payload = create_royalty_report_payload(
        agreement["id"], licensee["id"], lines=[make_report_line(gross_sales_cents=1000)]
    )
    resp = api.create_royalty_report(payload, make_licensee_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_report_requires_active_agreement_still_draft(api, analyst_headers):
    """PRD section 3.2: "Royalty report submission and sublicense requests
    require the agreement `ACTIVE`. ... Any of these operations attempted
    against an agreement outside its permitted status set is rejected with
    `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)." A DRAFT agreement is outside the
    permitted set just as a SUSPENDED one is.

    Design: Difficulty/cross_entity_state_dependency/report_requires_active_agreement
    """
    licensee = create_licensee()
    agreement = create_draft_agreement(licensee, patent_reference="US-44445-M2")
    payload = create_royalty_report_payload(
        agreement["id"], licensee["id"], lines=[make_report_line(gross_sales_cents=1000)]
    )
    resp = api.create_royalty_report(payload, make_licensee_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_occ_stale_version_on_agreement_patch(api, analyst_headers):
    """PRD section 2.7: "Amending a license agreement requires the request to
    carry `expected_agreement_version`, holding the agreement `version` the
    client last observed. If the agreement's current `version` has advanced
    past that value — because a prior amendment or lifecycle action
    legitimately rewrote the agreement — the amendment is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_agreement_patch
    """
    licensee = create_licensee(legal_name="Oc Co")
    agreement = create_draft_agreement(licensee, patent_reference="US-22231-V2")
    v1 = agreement["version"]

    resp = api.patch_agreement(
        agreement["id"],
        {"expected_agreement_version": v1, "minimum_period_royalty_cents": 7000},
        analyst_headers,
    )
    data = validate_success(resp)
    assert data["version"] == v1 + 1

    resp2 = api.patch_agreement(
        agreement["id"],
        {"expected_agreement_version": v1, "minimum_period_royalty_cents": 9000},
        analyst_headers,
    )
    validate_error(resp2, ApiErrorId.ERR_STALE_VERSION)
