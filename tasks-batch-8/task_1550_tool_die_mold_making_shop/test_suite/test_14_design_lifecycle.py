"""Tool design lifecycle: rejection loop, revision chains, and the
one-RELEASED-per-part rule (PRD §3.2)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_tool_design,
    assert_version_incremented,
    create_customer,
    create_design,
    get_success_data,
    review_design,
    submit_design,
    validate_error,
    validate_success,
)

ENGINEER = TEST_USERS["tooling_engineer_headers"]


def test_design_rejection_loops_back_to_draft(api):
    """PRD §3.2: "A `REJECTED` decision loops the design back from `SUBMITTED`
    to `DRAFT` so the customer can refine and resubmit."
    PRD §2.5: "Version bumps are themselves part of the contract: submitting
    or reviewing a design increments the design's `version`; creating a quote
    increments the design's `version` (through `quoted_count`); advancing,
    holding, resuming, filing an engineering change against, or recording a
    payment against a job each increments the job's `version`; and the
    credit-aging sweep increments the customer's `version` when it suspends
    one."

    Design: Corner/state_machines/design_rejection_loops_back_to_draft
    """
    customer = create_customer(company_name="Loop Co")
    design = create_design(customer["id"], part_number="PN-L1", tool_type="TRANSFER_DIE",
                           die_class="CLASS_102", cavity_count=2,
                           design_complexity_score=8)
    created_version = design["version"]

    submitted = submit_design(design["id"], customer["id"])
    assert submitted["status"] == "SUBMITTED"
    assert_version_incremented(submitted["version"], created_version)

    rejected = review_design(design["id"], "REJECTED", review_note="thin web at station 3")
    assert rejected["status"] == "DRAFT", (
        f"REJECTED must loop back to DRAFT, got {rejected['status']}"
    )
    assert_version_incremented(rejected["version"], submitted["version"])

    resubmitted = submit_design(design["id"], customer["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert_version_incremented(resubmitted["version"], rejected["version"])

    released = review_design(design["id"], "RELEASED")
    assert released["status"] == "RELEASED"
    assert_version_incremented(released["version"], resubmitted["version"])


def test_design_revise_self_referential_chain(api):
    """PRD §3.2: "The revision is a brand-new design in `DRAFT`: its
    `revision_number` is the source design's plus one, its
    `supersedes_design_id` points back at the source, and it inherits
    `part_number`, `customer_id`, and any of `cavity_count`,
    `design_complexity_score`, `die_class`, and `tool_type` that the caller
    did not override in the request."
    PRD §3.2: "When a release succeeds, the design named by this design's
    `supersedes_design_id`, if still `RELEASED`, cascades from `RELEASED` to
    `SUPERSEDED`, so at most one live revision of a part exists at any time."
    PRD §3.2: "A new design starts in `DRAFT` with `revision_number` 1, a null
    `supersedes_design_id`, and a `quoted_count` of zero."

    Design: Corner/state_machines/design_revise_self_referential_chain
    """
    customer = create_customer(company_name="Rev Co")
    d1 = create_design(customer["id"], part_number="PN-L2")
    assert d1["revision_number"] == 1
    assert d1["supersedes_design_id"] is None
    submit_design(d1["id"], customer["id"])
    d1 = review_design(d1["id"], "RELEASED")

    d2 = validate_success(
        api_client.revise_tool_design(d1["id"], {"design_complexity_score": 12}, ENGINEER),
        201,
    )
    assert_tool_design(d2)
    assert d2["status"] == "DRAFT"
    assert d2["revision_number"] == 2, (
        f"revision_number must be the source's plus one, got {d2['revision_number']}"
    )
    assert d2["supersedes_design_id"] == d1["id"]
    assert d2["design_complexity_score"] == 12  # overridden
    assert d2["cavity_count"] == 4  # inherited
    assert d2["part_number"] == "PN-L2"  # inherited
    assert d2["customer_id"] == customer["id"]  # inherited

    submit_design(d2["id"], customer["id"])
    d2 = review_design(d2["id"], "RELEASED")
    assert d2["status"] == "RELEASED"

    d1_after = get_success_data(api_client.get_tool_design(d1["id"], ENGINEER))
    assert d1_after["status"] == "SUPERSEDED", (
        f"releasing a revision must supersede its chain head, got {d1_after['status']}"
    )


def test_duplicate_released_design_per_part_rejected(api):
    """PRD §3.2: "A `RELEASED` decision is guarded: no other design for the
    same `customer_id` and `part_number` may already be `RELEASED`, unless
    that other design is the head of this design's supersedes chain — a
    violation is rejected with `ERR_DUPLICATE_RELEASED_DESIGN`."

    Design: Corner/state_machines/duplicate_released_design_per_part_rejected
    """
    customer = create_customer(company_name="Dup Co")
    design_a = create_design(customer["id"], part_number="PN-DUP")
    submit_design(design_a["id"], customer["id"])
    design_a = review_design(design_a["id"], "RELEASED")

    # Same (customer_id, part_number), but an independent design with no
    # supersedes link to the released one.
    design_b = create_design(customer["id"], part_number="PN-DUP",
                             die_class="CLASS_104", cavity_count=2,
                             design_complexity_score=5)
    submit_design(design_b["id"], customer["id"])

    res = api_client.review_tool_design(design_b["id"], {"decision": "RELEASED"}, ENGINEER)
    error = validate_error(res, ApiErrorId.ERR_DUPLICATE_RELEASED_DESIGN)
    assert error["error_id"] == "ERR_DUPLICATE_RELEASED_DESIGN"
    assert res.status_code == 409

    b_after = get_success_data(api_client.get_tool_design(design_b["id"], ENGINEER))
    assert b_after["status"] == "SUBMITTED"
    a_after = get_success_data(api_client.get_tool_design(design_a["id"], ENGINEER))
    assert a_after["status"] == "RELEASED"
