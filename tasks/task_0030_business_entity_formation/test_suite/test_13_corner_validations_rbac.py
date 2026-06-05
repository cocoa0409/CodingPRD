"""Corner — validations and RBAC sections.

ERR_UNAUTHENTICATED / ERR_UNAUTHORIZED rejection paths plus the standalone
business-rule rejections that the difficulty design does not absorb.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    setup_active_llc,
    create_forming_business_entity,
    create_registered_agent_for,
    create_draft_annual_report,
    create_foreign_agent,
    create_pending_foreign_qualification,
    make_filer_headers,
    make_state_admin_headers,
    make_compliance_officer_headers,
    make_anonymous_headers,
)


# ─── validations section ────────────────────────────────────────


def test_missing_x_user_role_returns_unauthenticated(api):
    """PRD §2.1: "Every request other than the formation-creation endpoint and
    the test-driving clock endpoint must carry two headers: `X-User-ID` (the
    caller's identifier) and `X-User-Role` (the caller's role string). Missing,
    empty, or unrecognized auth headers are rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/missing_x_user_role_returns_unauthenticated
    """
    res = api.create_annual_report(
        "00000000-0000-0000-0000-000000000000",
        {"period_year": 2024},
        headers={},
    )
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_filer_cannot_issue_ein_returns_unauthorized(api):
    """PRD §2.1: "A request whose role is well-formed but not on the target
    endpoint's authorized list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST /ein-applications/{id}/issue: Issue or reject an EIN
    application (payload may include `reject`). | `StateAdmin`"

    Design: Corner/validations/filer_cannot_issue_ein_returns_unauthorized
    """
    set_clock("2026-01-01T00:00:00Z")
    be = create_forming_business_entity(legal_name="UNIFORM LLC")
    create_registered_agent_for(be)
    # Create PENDING EIN.
    res_create = api.create_ein_application(
        be["id"],
        {"responsible_party_name": "R", "responsible_party_ssn_last4": "0300"},
        make_filer_headers(be["id"]),
    )
    ein_app = validate_success(res_create, 201)
    # Filer attempts issuance — not on the endpoint's authorized list.
    res = api.issue_ein_application(ein_app["id"], make_filer_headers(be["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_corp_rejects_operating_agreement(api):
    """PRD §3.4: "An `OperatingAgreement` is the governance document for an `LLC`
    or an `LP`; `CORP` entities do not produce one and any attempt to create an
    operating agreement against a `CORP` parent is rejected with
    `ERR_TEMPLATE_TYPE_MISMATCH`."

    Design: Corner/validations/corp_rejects_operating_agreement
    """
    set_clock("2026-01-01T00:00:00Z")
    be = create_forming_business_entity(
        legal_name="VICTOR INC", entity_type="CORP", formation_state_code="DE"
    )
    res = api.create_operating_agreement(
        be["id"],
        {
            "template_type": "MEMBER_MANAGED",
            "members_json": [{"name": "M1", "ownership_pct": 100}],
        },
        make_filer_headers(be["id"]),
    )
    validate_error(res, "ERR_TEMPLATE_TYPE_MISMATCH")


def test_foreign_qualification_same_state_returns_fq_same_state(api):
    """PRD §3.10: "The `foreign_state_code` is a two-letter uppercase state code
    from the supported set and must differ from the parent's `formation_state_code`
    — qualifying against your own home state is `ERR_FQ_SAME_STATE`."

    Design: Corner/validations/foreign_qualification_same_state_returns_fq_same_state
    """
    set_clock("2026-01-01T00:00:00Z")
    be, ra = setup_active_llc(legal_name="WHISKEY LLC", formation_state_code="DE")
    res = api.create_foreign_qualification(
        be["id"],
        {"foreign_state_code": "DE", "foreign_registered_agent_id": ra["id"]},
        make_filer_headers(be["id"]),
    )
    validate_error(res, "ERR_FQ_SAME_STATE")


def test_foreign_qualification_agent_state_mismatch(api):
    """PRD §3.10: "The `foreign_registered_agent_id` references a
    `RegisteredAgent`, which must be in `ACTIVE` status and whose
    `agent_state_code` must equal the `foreign_state_code`; failures of either
    condition are rejected with `ERR_FQ_AGENT_MISMATCH`."

    Design: Corner/validations/foreign_qualification_agent_state_mismatch
    """
    set_clock("2026-01-01T00:00:00Z")
    be, ra_de = setup_active_llc(legal_name="XRAY LLC", formation_state_code="DE")
    # Per PRD §3.10 the agent_state_code constraint is stated in the creation
    # paragraph; supplying a DE agent for a CA foreign-state slot fails at
    # creation with ERR_FQ_AGENT_MISMATCH.
    res = api.create_foreign_qualification(
        be["id"],
        {"foreign_state_code": "CA", "foreign_registered_agent_id": ra_de["id"]},
        make_filer_headers(be["id"]),
    )
    validate_error(res, "ERR_FQ_AGENT_MISMATCH")


def test_operating_agreement_invalid_owner_sum(api):
    """PRD §3.4: "The sum of all members' `ownership_pct` values must equal
    exactly 100 — neither 99 nor 101 is acceptable. Violations of any of these
    member-list rules are rejected with `ERR_OPERATING_AGREEMENT_INVALID`."

    Design: Corner/validations/operating_agreement_invalid_owner_sum
    """
    set_clock("2026-01-01T00:00:00Z")
    be = create_forming_business_entity(
        legal_name="YANK LLC", entity_type="LLC", formation_state_code="DE"
    )
    res = api.create_operating_agreement(
        be["id"],
        {
            "template_type": "MEMBER_MANAGED",
            "members_json": [
                {"name": "M1", "ownership_pct": 60},
                {"name": "M2", "ownership_pct": 30},
            ],
        },
        make_filer_headers(be["id"]),
    )
    validate_error(res, "ERR_OPERATING_AGREEMENT_INVALID")


def test_franchise_tax_in_arrears_blocks_foreign_qualification_approval(api):
    """PRD §3.10: "every prior `AnnualReport` for the parent whose `period_year`
    is strictly less than the current clock year must already be in `FILED` or
    `VOIDED` (an arrears report blocks approval with `ERR_FRANCHISE_TAX_IN_ARREARS`)."

    Design: Corner/validations/franchise_tax_in_arrears_blocks_foreign_qualification_approval
    """
    set_clock("2024-12-01T00:00:00Z")
    be, _ = setup_active_llc(legal_name="ZULU LLC", formation_state_code="DE")
    create_draft_annual_report(be, 2024)
    ca_agent = create_foreign_agent(be, foreign_state_code="CA")
    fq = create_pending_foreign_qualification(be, "CA", ca_agent["id"])
    # Advance past April-15-2025 → AR DELINQUENT, BE → DELINQUENT.
    set_clock("2025-05-01T00:00:00Z")
    res = api.approve_foreign_qualification(fq["id"], make_state_admin_headers())
    validate_error(res, "ERR_FRANCHISE_TAX_IN_ARREARS")


# ─── rbac section ───────────────────────────────────────────────


def test_anonymous_cannot_dissolve_entity(api):
    """PRD §2.1: "`Anonymous` — a pre-formation requester with no persisted
    identity. `X-User-ID` is an opaque token not tied to any stored entity; the
    server does not compare it to any record's `id`. `Anonymous` can create a
    new `BusinessEntity` and read the public formation registry, and nothing
    else."

    Design: Corner/rbac/anonymous_cannot_dissolve_entity
    """
    set_clock("2026-01-01T00:00:00Z")
    be, _ = setup_active_llc(legal_name="DDD LLC", formation_state_code="DE")
    res = api.dissolve_business_entity(be["id"], make_anonymous_headers())
    validate_error(res, "ERR_UNAUTHORIZED")


def test_compliance_officer_cannot_file_annual_report(api):
    """PRD §3.7: "An `AnnualReport` is created by a `Filer` against a
    `BusinessEntity` with a single payload field"
    PRD §2.1: "A request whose role is well-formed but not on the target
    endpoint's authorized list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST | `/annual-reports/{id}/file` | File an annual report. | `Filer`"

    Design: Corner/rbac/compliance_officer_cannot_file_annual_report
    """
    set_clock("2025-03-01T00:00:00Z")
    be, _ = setup_active_llc(legal_name="EEE LLC", formation_state_code="DE")
    ar = create_draft_annual_report(be, 2024)
    res = api.file_annual_report(ar["id"], make_compliance_officer_headers())
    validate_error(res, "ERR_UNAUTHORIZED")


def test_state_admin_cannot_resign_registered_agent(api):
    """PRD §3.3: "Voluntary resignation is the other path out of `ACTIVE`. A
    `Filer` can resign a `RegisteredAgent`"
    PRD §2.1: "A request whose role is well-formed but not on the target
    endpoint's authorized list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST | `/registered-agents/{id}/resign` | Voluntary resignation of a registered agent. | `Filer`"

    Design: Corner/rbac/state_admin_cannot_resign_registered_agent
    """
    set_clock("2026-01-01T00:00:00Z")
    be, ra = setup_active_llc(legal_name="FFF LLC", formation_state_code="DE")
    res = api.resign_registered_agent(ra["id"], make_state_admin_headers())
    validate_error(res, "ERR_UNAUTHORIZED")
