"""Cross-entity state dependencies: a notice gated on its representative's own
window, and a letter gated on a cluster total the case never names."""

from test_helpers import (
    ADMIN,
    ANALYST,
    SELLER_STATUS_ACTIVE,
    SELLER_STATUS_UNDER_INVESTIGATION,
    ApiErrorId,
    add_business_days,
    assert_instant_equals,
    assert_seller_strikes,
    create_case,
    create_representative,
    create_seller,
    expected_decision_due_at,
    make_authorized_representative_headers,
    read_case,
    read_listing,
    read_seller,
    read_takedown,
    send_cease_desist,
    set_clock,
    setup_drafted_takedown,
    setup_removed_takedown,
    setup_second_removal_on_same_seller,
    submit_takedown,
    validate_error,
    validate_success,
)


def test_notice_cannot_be_filed_before_its_designation_window_opens(api):
    """PRD §3.8: "The acting designation must be `DESIGNATED` and the logical clock must fall inside its half-open effective window, else `ERR_REPRESENTATIVE_NOT_EFFECTIVE` (HTTP 409)."
    PRD §3.2: "The designation window is **half-open**: it includes `effective_from` and excludes `effective_to`, and an omitted or null `effective_to` means the window never closes."
    PRD §3.8: "On a successful filing, `submitted_by_rep_id` is stamped with the acting `X-User-ID`, `submitted_at` is stamped from the logical clock, `round_number` becomes 1, and `decision_due_at` is computed by advancing `submitted_at` by the marketplace's own service-level allowance — five business days for `AMZ`, eight for `EBY`, ten for `WLM` — read from the filing enrolment's `marketplace_code`."
    PRD §2.9: "Evaluation stops there and nothing is persisted — not even a value the server had already computed."

    Design: Difficulty/cross_entity_state_dependency/takedown_submit_gated_on_the_designations_own_effective_window
    """
    ctx = setup_drafted_takedown(
        api, clock="2026-08-05T09:00:00Z",
        representative={"effective_from": "2026-08-20T00:00:00Z",
                        "effective_to": "2026-08-30T00:00:00Z",
                        "power_of_attorney_ref": "POA-WINDOW"})
    rep_headers = make_authorized_representative_headers(ctx["representative"]["id"])
    assert ctx["takedown"]["status"] == "DRAFT"
    assert ctx["representative"]["designation_status"] == "DESIGNATED"

    too_early = api.submit_takedown(ctx["takedown"]["id"], headers=rep_headers)
    validate_error(too_early, ApiErrorId.REPRESENTATIVE_NOT_EFFECTIVE, 409)

    untouched = read_takedown(api, ctx["takedown"]["id"])
    assert untouched["status"] == "DRAFT", f"got {untouched['status']}"
    assert untouched["round_number"] == 0
    assert untouched["submitted_by_rep_id"] is None
    assert untouched["submitted_at"] is None
    assert untouched["decision_due_at"] is None
    assert untouched["version"] == ctx["takedown"]["version"]
    assert read_listing(api, ctx["listing"]["id"])["enforcement_status"] == "CLAIM_OPEN"

    # The lower bound is inclusive, so the very first instant of the window files.
    set_clock(api, "2026-08-20T00:00:00Z")
    filed = submit_takedown(api, ctx["takedown"]["id"], ctx["representative"]["id"])
    assert filed["status"] == "SUBMITTED", f"got {filed['status']}"
    assert filed["round_number"] == 1
    assert filed["submitted_by_rep_id"] == ctx["representative"]["id"]
    assert_instant_equals(filed["submitted_at"], "2026-08-20T00:00:00Z", "submitted_at")
    assert_instant_equals(filed["decision_due_at"],
                          expected_decision_due_at("2026-08-20T00:00:00Z"), "decision_due_at")
    assert_instant_equals(filed["decision_due_at"], "2026-08-27T00:00:00Z", "decision_due_at")


def test_a_closed_window_and_a_revoked_designation_both_block_the_filing(api):
    """PRD §3.2: "The designation window is **half-open**: it includes `effective_from` and excludes `effective_to`, and an omitted or null `effective_to` means the window never closes."
    PRD §3.2: "A `BrandAdministrator` may revoke a designation at any time while it is `DESIGNATED`, optionally supplying a `reason_code` for the audit trail; the row moves `DESIGNATED → REVOKED`, `revoked_at` is stamped from the logical clock, and its `version` is incremented by 1."
    PRD §3.8: "The acting designation must be `DESIGNATED` and the logical clock must fall inside its half-open effective window, else `ERR_REPRESENTATIVE_NOT_EFFECTIVE` (HTTP 409)."
    PRD §3.2: "Because the end is exclusive, **adjacency is allowed**: a window ending at exactly the instant the next begins is not a conflict."

    Design: Difficulty/cross_entity_state_dependency/takedown_submit_gated_on_the_designations_own_effective_window
    """
    ctx = setup_drafted_takedown(
        api, clock="2026-08-05T09:00:00Z",
        representative={"effective_from": "2026-08-01T00:00:00Z",
                        "effective_to": "2026-08-10T00:00:00Z",
                        "power_of_attorney_ref": "POA-EARLY"})
    successor = create_representative(
        api, ctx["enrollment"]["id"], authority_scope="SUBMIT_TAKEDOWN",
        effective_from="2026-08-10T00:00:00Z", effective_to="2027-08-01T00:00:00Z",
        power_of_attorney_ref="POA-LATE")
    revoked = validate_success(
        api.revoke_representative(successor["id"], "REPLACED", headers=ADMIN), 200)
    assert revoked["designation_status"] == "REVOKED", f"got {revoked['designation_status']}"
    assert_instant_equals(revoked["revoked_at"], "2026-08-05T09:00:00Z", "revoked_at")

    # The upper bound is exclusive, so the successor's first instant retires the incumbent.
    set_clock(api, "2026-08-10T00:00:00Z")
    expired = api.submit_takedown(
        ctx["takedown"]["id"],
        headers=make_authorized_representative_headers(ctx["representative"]["id"]))
    validate_error(expired, ApiErrorId.REPRESENTATIVE_NOT_EFFECTIVE, 409)

    withdrawn_authority = api.submit_takedown(
        ctx["takedown"]["id"],
        headers=make_authorized_representative_headers(successor["id"]))
    validate_error(withdrawn_authority, ApiErrorId.REPRESENTATIVE_NOT_EFFECTIVE, 409)

    untouched = read_takedown(api, ctx["takedown"]["id"])
    assert untouched["status"] == "DRAFT", f"got {untouched['status']}"
    assert untouched["submitted_by_rep_id"] is None
    assert untouched["version"] == ctx["takedown"]["version"]


def test_cease_desist_reads_the_cluster_rollup_of_an_unnamed_sibling(api):
    """PRD §3.9: "And the case's seller must be `UNDER_INVESTIGATION` or `BLOCKED`, because correspondence may only be aimed at an escalated seller; a still-`ACTIVE` seller is refused with `ERR_SELLER_NOT_UNDER_INVESTIGATION` (HTTP 422)."
    PRD §3.3: "`cluster_strike_points` counts strikes across the whole alias cluster: the cluster is the root — which is the row's own `canonical_seller_id` when it has one, and otherwise the row's own `id` — unioned with every row that names that root as its `canonical_seller_id`."
    PRD §3.3: "A seller with zero standalone points can therefore still be blocked on the strength of a sibling's history."
    PRD §3.3: "Every recompute rewrites `status` for **every member of the cluster** from the cluster total, so all members always share the same status, and every member whose status or point totals actually changed has its `version` incremented by 1."
    PRD §3.9: "Sending the letter stamps `cease_desist_sent_by_rep_id` with the acting `X-User-ID` — this is the pin that the segregation-of-duties rule reads later — sets `cd_sent_at` from the logical clock, persists `letter_ref`, computes `cd_response_due_at` by advancing `cd_sent_at` by fourteen business days, and increments the case's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/cease_desist_gated_on_a_cluster_rollup_of_a_seller_the_case_never_names
    """
    ctx = setup_removed_takedown(api, clock="2026-08-10T09:00:00Z")
    ctx = setup_second_removal_on_same_seller(api, ctx, clock="2026-08-17T09:00:00Z", tag="2")
    canonical = create_seller(api, seller_ref="A1CANONICAL")
    assert_seller_strikes(canonical, 0.00, 0.00, SELLER_STATUS_ACTIVE)

    validate_success(api.link_alias(ctx["seller"]["id"], canonical["id"],
                                    canonical["version"], headers=ANALYST), 200)

    root = read_seller(api, canonical["id"])
    assert_seller_strikes(root, 0.00, 25.10, SELLER_STATUS_UNDER_INVESTIGATION)

    case = create_case(api, ctx["brand"]["id"], canonical["id"])
    assert case["correspondence_status"] == "NONE"
    assert case["case_status"] == "OPEN"
    assert case["originating_takedown_id"] is None, (
        "A manually opened case names no originating notice")

    sent = send_cease_desist(api, case["id"], ctx["representative"]["id"], "CD-CLUSTER-1")

    assert sent["correspondence_status"] == "CD_SENT", f"got {sent['correspondence_status']}"
    assert sent["case_status"] == "OPEN", f"got {sent['case_status']}"
    assert sent["cease_desist_sent_by_rep_id"] == ctx["representative"]["id"]
    assert sent["letter_ref"] == "CD-CLUSTER-1"
    assert_instant_equals(sent["cd_sent_at"], "2026-08-17T09:00:00Z", "cd_sent_at")
    assert_instant_equals(sent["cd_response_due_at"], "2026-09-04T09:00:00Z",
                          "cd_response_due_at")
    assert_instant_equals(sent["cd_response_due_at"],
                          add_business_days("2026-08-17T09:00:00Z", 14), "cd_response_due_at")
    assert sent["version"] == case["version"] + 1
    assert sent["seller_id"] == canonical["id"], (
        "The case still names only the canonical seller")


def test_the_letter_waits_until_the_siblings_points_escalate_the_root(api):
    """PRD §3.9: "And the case's seller must be `UNDER_INVESTIGATION` or `BLOCKED`, because correspondence may only be aimed at an escalated seller; a still-`ACTIVE` seller is refused with `ERR_SELLER_NOT_UNDER_INVESTIGATION` (HTTP 422)."
    PRD §3.3: "To make the thresholds concrete: a single fresh takedown-removal strike is 12.55 points and leaves the seller `ACTIVE`; two fresh takedown-removal strikes total 25.10 and escalate the seller to `UNDER_INVESTIGATION`; one fresh seizure-confirmed strike is 25.15 and escalates on its own; one fresh cease-and-desist-ignored strike is 5.05."
    PRD §3.3: "`status` is a pure function of `cluster_strike_points` and of nothing else."
    PRD §2.9: "**Priority 42** — the case's seller is `UNDER_INVESTIGATION` or `BLOCKED`, else `ERR_SELLER_NOT_UNDER_INVESTIGATION` (422). Applies to sending a cease-and-desist letter."

    Design: Difficulty/cross_entity_state_dependency/cease_desist_gated_on_a_cluster_rollup_of_a_seller_the_case_never_names
    """
    ctx = setup_removed_takedown(api, clock="2026-08-10T09:00:00Z")
    canonical = create_seller(api, seller_ref="A1CANONICAL")
    validate_success(api.link_alias(ctx["seller"]["id"], canonical["id"],
                                    canonical["version"], headers=ANALYST), 200)
    assert_seller_strikes(read_seller(api, canonical["id"]), 0.00, 12.55, SELLER_STATUS_ACTIVE)

    case = create_case(api, ctx["brand"]["id"], canonical["id"])
    too_soon = api.send_cease_desist(
        case["id"], "CD-CLUSTER-1",
        headers=make_authorized_representative_headers(ctx["representative"]["id"]))
    validate_error(too_soon, ApiErrorId.SELLER_NOT_UNDER_INVESTIGATION, 422)

    unchanged = read_case(api, case["id"])
    assert unchanged["correspondence_status"] == "NONE", f"got {unchanged['correspondence_status']}"
    assert unchanged["cd_sent_at"] is None
    assert unchanged["cd_response_due_at"] is None
    assert unchanged["version"] == case["version"]

    ctx = setup_second_removal_on_same_seller(api, ctx, clock="2026-08-17T09:00:00Z", tag="2")
    assert_seller_strikes(read_seller(api, canonical["id"]), 0.00, 25.10,
                          SELLER_STATUS_UNDER_INVESTIGATION)

    sent = send_cease_desist(api, case["id"], ctx["representative"]["id"], "CD-CLUSTER-1")
    assert sent["correspondence_status"] == "CD_SENT", f"got {sent['correspondence_status']}"
    assert_instant_equals(sent["cd_sent_at"], "2026-08-17T09:00:00Z", "cd_sent_at")
    assert_instant_equals(sent["cd_response_due_at"], "2026-09-04T09:00:00Z",
                          "cd_response_due_at")
