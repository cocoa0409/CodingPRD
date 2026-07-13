"""Pre-built role headers for every role in the PRD (§2.1).

`FacilityOperator` is entity-backed: its `X-User-ID` must equal the acting
Facility's `id` for ownership-gated writes. Use `make_facility_operator_headers`
with the real facility id for those calls; the shared constant below is only a
fallback for tests that do not exercise ownership.

The remaining roles (PermitReviewer, Inspector, EnforcementOfficer, Anonymous)
are opaque — their `X-User-ID` is not tied to any entity, so the shared
constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "facility_operator_headers": build_user_headers("test-operator-1", "FacilityOperator"),
    "permit_reviewer_headers": build_user_headers("test-reviewer-1", "PermitReviewer"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "enforcement_officer_headers": build_user_headers("test-enforcement-1", "EnforcementOfficer"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


def make_facility_operator_headers(facility_id: str) -> dict:
    """For FacilityOperator (entity_backed:Facility). Pass the acting Facility's
    id as X-User-ID whenever the call is an operator-owned, ownership-gated write."""
    return build_user_headers(facility_id, "FacilityOperator")
