"""Corner — endpoints, errors, and consistency_model sections.

FK-filtered listing, ERR_STALE_VERSION direct trigger, and the immediate-
consistency claim that a file response shows the post-FILED state.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    setup_active_llc,
    create_forming_business_entity,
    create_draft_annual_report,
    file_annual_report,
    create_registered_agent_for,
    make_filer_headers,
    make_compliance_officer_headers,
)


# ─── endpoints section ──────────────────────────────────────────


def test_list_filtered_by_fk_business_entity_id_returns_only_those_children(api):
    """PRD §4: "GET /business-entities/{id}/annual-reports: List annual reports
    under an entity (filters: `status`, `period_year`, `limit`, `offset`)."
    PRD §2.5: "When a path looks like
    `/business-entities/{business_entity_id}/foreign-qualifications/{foreign_qualification_id}`,
    the parent `BusinessEntity` is resolved first"

    Design: Corner/endpoints/list_filtered_by_fk_business_entity_id_returns_only_those_children
    """
    set_clock("2025-03-01T00:00:00Z")
    be1, _ = setup_active_llc(legal_name="AAA LLC", formation_state_code="DE")
    be2, _ = setup_active_llc(legal_name="BBB LLC", formation_state_code="DE")
    ar1 = create_draft_annual_report(be1, 2024)
    ar2 = create_draft_annual_report(be2, 2024)
    res = api.list_annual_reports(be1["id"], make_compliance_officer_headers())
    rows = validate_success(res, 200)
    ids = {r["id"] for r in rows}
    assert ar1["id"] in ids, "AR for be1 must appear under be1's children listing"
    assert ar2["id"] not in ids, "AR for be2 must NOT appear under be1's children listing"


# ─── errors section ─────────────────────────────────────────────


def test_err_stale_version_triggerable_on_registered_agent_create(api):
    """PRD §2.7: "The server compares that value to the `BusinessEntity`'s current
    `version` at the moment of the write; if they do not match — that is, if some
    other writer has advanced the `BusinessEntity`'s `version` between the
    client's read and the client's write — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/err_stale_version_triggerable_on_registered_agent_create
    """
    set_clock("2026-01-01T00:00:00Z")
    be = create_forming_business_entity(legal_name="CCC LLC")
    be_v0 = be["version"]
    # First create succeeds with the current version; advances version.
    create_registered_agent_for(be)
    # Replay the now-stale version (be_v0) — must fail with ERR_STALE_VERSION.
    res = api.create_registered_agent(
        be["id"],
        {
            "agent_name": "DE Agent 2",
            "agent_type": "COMMERCIAL",
            "agent_state_code": "DE",
            "expected_business_entity_version": be_v0,
        },
        make_filer_headers(be["id"]),
    )
    validate_error(res, "ERR_STALE_VERSION")


# ─── consistency_model section ──────────────────────────────────


def test_immediate_consistency_file_response_reflects_new_state(api):
    """PRD §3.7: "Filing a report — moving it from either `DRAFT` or `DELINQUENT`
    to `FILED` — re-evaluates the assessed franchise tax against the parent's
    current `revenue_band` (the assessed-final variant in §3.8), computes the
    `late_fee_cents` from the current clock UTC against the deadline (§3.9),
    stamps `filed_at` from the current clock UTC"

    Design: Corner/consistency_model/immediate_consistency_file_response_reflects_new_state
    """
    set_clock("2025-03-01T00:00:00Z")
    be, _ = setup_active_llc(legal_name="GGG LLC", formation_state_code="DE")
    ar = create_draft_annual_report(be, 2024)
    filed = file_annual_report(be, ar["id"])
    # The same response body carries the post-FILED state — no read-after-write.
    assert filed["status"] == "FILED"
    # DE LLC ZERO at 2025-03-01: base=30000, mult=100, raw=30000, floor=17500 -> 30000.
    assert filed["franchise_tax_amount_cents"] == 30000
    # PRD §2.4: timestamps are ISO 8601 UTC. The test pins the clock to
    # 2025-03-01T00:00:00Z; filed_at must carry that instant in any
    # PRD-compliant ISO 8601 UTC form (with or without fractional digits).
    assert filed["filed_at"].startswith("2025-03-01T00:00:00")
    assert filed["filed_at"].endswith("Z")
