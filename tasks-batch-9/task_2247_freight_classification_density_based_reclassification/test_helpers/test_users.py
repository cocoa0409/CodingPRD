"""Pre-built role headers for the six roles the PRD declares.

Four roles are opaque -- `PricingAnalyst`, `FreightInspector`,
`ClassificationAuditor` and `DisputeReviewer` -- so a shared constant header is
the canonical form for them.  Two roles are entity-backed: for
`TerminalOperator` the `X-User-ID` is the acting terminal's own `id`, and for
`Shipper` it is the acting shipper account's own `id`.  Any ownership-gated call
made in those two capacities MUST use the per-instance builder below with the
real entity id, never a shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

# --------------------------------------------------------------------------
# Shared constants.
#
# Safe for the four opaque roles.  For the two entity-backed roles these are a
# fallback usable ONLY by tests whose expected outcome does not depend on the
# caller owning the subject resource (authentication failures, role-permission
# failures, unknown-identifier failures).
# --------------------------------------------------------------------------

TEST_USERS = {
    "pricing_analyst_headers": build_user_headers("analyst-1", "PricingAnalyst"),
    "freight_inspector_headers": build_user_headers("insp-1", "FreightInspector"),
    "classification_auditor_headers": build_user_headers("aud-1", "ClassificationAuditor"),
    "dispute_reviewer_headers": build_user_headers("rev-1", "DisputeReviewer"),
    # entity_backed roles -- non-ownership tests only.
    "terminal_operator_headers": build_user_headers("terminal-operator-1", "TerminalOperator"),
    "shipper_headers": build_user_headers("shipper-1", "Shipper"),
}


# --------------------------------------------------------------------------
# Per-instance builders.
# --------------------------------------------------------------------------

def make_terminal_operator_headers(user_id: str) -> dict:
    """Headers for a `TerminalOperator`.

    `X-User-ID` doubles as the acting terminal's `id`, so pass the real
    `Terminal.id` whenever the call is ownership-gated (dock capture).
    """
    return build_user_headers(user_id, "TerminalOperator")


def make_shipper_headers(user_id: str) -> dict:
    """Headers for a `Shipper`.

    `X-User-ID` doubles as the acting shipper account's `id`, so pass the real
    `Customer.id` whenever the call is ownership-gated (tender, line addition,
    dispute filing, dispute supplementation, shipper-owned reads).
    """
    return build_user_headers(user_id, "Shipper")


def make_pricing_analyst_headers(user_id: str = "analyst-1") -> dict:
    """Headers for an opaque `PricingAnalyst` operator identifier."""
    return build_user_headers(user_id, "PricingAnalyst")


def make_freight_inspector_headers(user_id: str = "insp-1") -> dict:
    """Headers for an opaque `FreightInspector`; recorded as `inspector_user_id`."""
    return build_user_headers(user_id, "FreightInspector")


def make_classification_auditor_headers(user_id: str = "aud-1") -> dict:
    """Headers for an opaque `ClassificationAuditor`; recorded as
    `accepted_by_user_id` and `issued_by_user_id`."""
    return build_user_headers(user_id, "ClassificationAuditor")


def make_dispute_reviewer_headers(user_id: str = "rev-1") -> dict:
    """Headers for an opaque `DisputeReviewer`; recorded as `reviewer_user_id`."""
    return build_user_headers(user_id, "DisputeReviewer")


def make_headers_without_role(user_id: str = "analyst-1") -> dict:
    """Headers carrying only `X-User-ID` -- the role header is omitted entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_without_user_id(role: str) -> dict:
    """Headers carrying only `X-User-Role` -- the user header is omitted entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
