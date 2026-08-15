"""Anti-splitting rolling-window aggregate (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    create_department,
    create_requisition_draft,
    create_vendor,
    get_success_data,
    make_requester_headers,
    requisition_line,
    submit_requisition_ok,
    validate_error,
    walk_approval_chain,
)
from test_helpers.fixtures import ADMIN


def _two_approved_1200k(api):
    """Two APPROVED same-department same-vendor requisitions of 1,200,000 each."""
    dept = create_department(name="Philosophy")
    vendor = create_vendor(legal_name="PrintCo")
    ids = []
    for desc in ("journals", "binding"):
        req = create_requisition_draft(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="PHI", description=desc,
                unit_price_cents=1200000, cost_category="SERVICES",
            )],
        )
        submit_requisition_ok(req["id"])
        walk_approval_chain(req["id"])
        ids.append(req["id"])
    return dept, vendor, ids


class TestAntiSplitInclusiveBoundary:
    def test_rolling_sum_reaching_threshold_rejected(self, api):
        """PRD §3.3: "If the rolling sum plus the new requisition's own total
        reaches 2,500,000 cents — equality included — the submission is rejected
        with `ERR_BID_SPLITTING_DETECTED`."

        Design: Difficulty/boundary_precision_check/anti_split_rolling_sum_inclusive_boundary
        """
        dept, vendor, _ = _two_approved_1200k(api)
        r3 = create_requisition_draft(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="PHI", description="reprints",
                unit_price_cents=100000, cost_category="SERVICES",
            )],
        )
        resp = api.submit_requisition(r3["id"], make_requester_headers("req-user-1"))
        # 1,200,000 + 1,200,000 + 100,000 == 2,500,000 — equality triggers.
        validate_error(resp, ApiErrorId.ERR_BID_SPLITTING_DETECTED, 409)
        live = get_success_data(api.get_requisition(r3["id"], ADMIN))
        assert live["status"] == "DRAFT"

    def test_rolling_sum_one_cent_below_threshold_submits(self, api):
        """PRD §3.3: "Whenever a submitted requisition does not ride a contract,
        names a vendor, and totals less than 25,000 dollars, the system sums
        `total_cents` over the same department's other requisitions to the same
        vendor whose `submitted_at` falls inside the rolling window that ends at
        the logical clock and begins thirty days earlier — both ends of the
        window inclusive — and whose status is `SUBMITTED`, `APPROVED`, or
        `PO_ISSUED`."
        PRD §3.3: "If the rolling sum plus the new requisition's own total
        reaches 2,500,000 cents — equality included — the submission is rejected
        with `ERR_BID_SPLITTING_DETECTED`." — one cent under, it submits.

        Design: Difficulty/boundary_precision_check/anti_split_rolling_sum_inclusive_boundary
        """
        dept, vendor, _ = _two_approved_1200k(api)
        # A rejected (still-DRAFT) requisition never enters the sum.
        r3 = create_requisition_draft(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="PHI", description="reprints",
                unit_price_cents=100000, cost_category="SERVICES",
            )],
        )
        rejected = api.submit_requisition(
            r3["id"], make_requester_headers("req-user-1")
        )
        validate_error(rejected, ApiErrorId.ERR_BID_SPLITTING_DETECTED, 409)

        r4 = create_requisition_draft(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="PHI", description="reprints-sm",
                unit_price_cents=99999, cost_category="SERVICES",
            )],
        )
        submitted = submit_requisition_ok(r4["id"])
        # 2,400,000 + 99,999 == 2,499,999 — one cent under, accepted.
        assert submitted["status"] == "SUBMITTED"
        assert submitted["total_cents"] == 99999
