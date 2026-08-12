"""Compliance review: the seven-hop suspension cascade, gate precedence and resolution."""

from test_helpers import (
    CMRA_OPERATOR,
    ApiErrorId,
    assert_usage_ledger_entry,
    disposition_payload,
    lodge_disposition,
    log_and_match_letter,
    mail_item_version,
    make_compliance_officer_headers,
    open_billing_cycle,
    open_compliance_review,
    read_mail_item,
    read_recipient,
    resolve_compliance_review,
    set_clock,
    setup_releasable_box,
    suspend_compliance_review,
    validate_error,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# The seven-hop cascade
# ==========================================================================
def _setup_frozen_piece_under_review():
    """A piece received on 2026-05-01 with a pending SHRED, at clock 2026-05-10."""
    ctx = setup_releasable_box(
        "G-701",
        "Kay Freeze",
        holder_email="kay@example.com",
        plan_overrides={"name": "Plus Tight Storage", "included_storage_days": 2},
    )
    item = log_and_match_letter(ctx)
    disposition = lodge_disposition(ctx, item["id"], "SHRED")
    set_clock("2026-05-10T00:00:00Z")
    review = open_compliance_review(ctx["box_id"], "USPS_AUDIT", "co-1")
    ctx["item_id"] = item["id"]
    ctx["disposition_id"] = disposition["id"]
    ctx["review_id"] = review["id"]
    return ctx


def test_suspension_moves_the_review_and_the_mailbox_together(api):
    """PRD §3.11: "**Hop 1.** The review moves `OPEN → SUSPENDED`, and
    `ComplianceReview.version` is bumped by one."
    PRD §3.11: "**Hop 2.** Because the review suspended, the mailbox's `service_status`
    moves `ACTIVE → SUSPENDED` with `suspended_reason` set to `COMPLIANCE_REVIEW` and
    `release_gate_state` set to `GATED_SUSPENDED`, and its `compliance_status` moves
    `UNDER_REVIEW → NON_COMPLIANT`."

    Design: Difficulty/transitive_cascade/compliance_suspension_seven_hop_cascade
    """
    ctx = _setup_frozen_piece_under_review()

    review = validate_success(
        api.suspend_compliance_review(ctx["review_id"], make_compliance_officer_headers("co-1"))
    )
    assert review["status"] == "SUSPENDED"

    box = validate_success(api.get_box(ctx["box_id"], CMRA_OPERATOR))
    assert box["service_status"] == "SUSPENDED"
    assert box["compliance_status"] == "NON_COMPLIANT"
    assert box["suspended_reason"] == "COMPLIANCE_REVIEW"
    assert box["release_gate_state"] == "GATED_SUSPENDED"


def test_suspension_cancels_the_pending_request_and_resumes_the_storage_axis(api):
    """PRD §3.11: "**Hop 3.** Because the mailbox is now suspended, every disposition
    request whose piece belongs to this mailbox and whose status is `PENDING` moves to
    `CANCELLED` with `resolution_reason` `GATE_SUSPENSION`, each bumping its own
    `version` by one."
    PRD §3.11: "**Hop 5.** Because those pieces re-entered `HELD`, their storage axis is
    re-evaluated, having been suspended while they sat in `PENDING_DISPOSITION`. Any
    piece whose total custody days is **strictly greater than** the tier's
    `included_storage_days` runs `FREE_WINDOW → ACCRUING`, appending a usage-ledger entry
    of `unit_type` `STORAGE_DAY` into the mailbox's `OPEN` billing cycle and incrementing
    that cycle's `storage_days_consumed`."

    Design: Difficulty/transitive_cascade/compliance_suspension_seven_hop_cascade
    """
    ctx = _setup_frozen_piece_under_review()
    suspend_compliance_review(ctx["review_id"], "co-1")

    dispositions = validate_success(api.list_dispositions(ctx["item_id"], CMRA_OPERATOR))
    cancelled = next(d for d in dispositions if d["id"] == ctx["disposition_id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["resolution_reason"] == "GATE_SUSPENSION"

    piece = read_mail_item(ctx["item_id"])
    assert piece["storage_status"] == "ACCRUING"
    assert piece["free_storage_days_used"] == 2
    assert piece["billable_storage_days"] == 7
    assert piece["billing_status"] == "METERED"

    cycle = open_billing_cycle(ctx["box_id"])
    assert cycle["storage_days_consumed"] == 7
    entries, meta = validate_paginated(
        api.list_cycle_usage_entries(
            cycle["id"], CMRA_OPERATOR, params={"unit_type": "STORAGE_DAY"}
        )
    )
    assert meta["total_count"] == 1
    entry = entries[0]
    assert_usage_ledger_entry(entry)
    assert entry["billing_cycle_id"] == cycle["id"]
    assert entry["mail_item_id"] == ctx["item_id"]
    assert entry["tranche"] == "OVERAGE"
    assert entry["quantity"] == 7
    assert entry["unit_rate_cents"] == 30
    assert entry["amount_cents"] == 210


def test_suspension_suspends_the_roster_and_pushes_the_piece_back_to_awaiting_clearance(api):
    """PRD §3.11: "**Hop 6.** Because the mailbox is suspended, every roster member with
    `roster_status` `AUTHORIZED` moves to `SUSPENDED`, each bumping its own `version` by
    one."
    PRD §3.11: "**Hop 7.** Because those members left `AUTHORIZED`, their
    `release_eligibility` re-derives `RELEASABLE → BLOCKED`, which moves every piece of
    theirs whose `handling_status` is `HELD` back to `AWAITING_CLEARANCE`, each such
    piece bumping its `version` by one."
    PRD §3.3: "5. The member's `roster_status` is `AUTHORIZED`. Otherwise `BLOCKED` with
    `blocked_reason` `ROSTER_NOT_AUTHORIZED`."

    Design: Difficulty/transitive_cascade/compliance_suspension_seven_hop_cascade
    """
    ctx = _setup_frozen_piece_under_review()
    suspend_compliance_review(ctx["review_id"], "co-1")

    member = read_recipient(ctx["recipient_id"])
    assert member["roster_status"] == "SUSPENDED"
    assert member["release_eligibility"] == "BLOCKED"
    assert member["blocked_reason"] == "ROSTER_NOT_AUTHORIZED"

    assert read_mail_item(ctx["item_id"])["handling_status"] == "AWAITING_CLEARANCE"


# ==========================================================================
# Gate precedence
# ==========================================================================
def _setup_suspended_box_with_blocked_member():
    ctx = setup_releasable_box("K-1101", "Oda Gate", holder_email="oda@example.com")
    item = log_and_match_letter(ctx)
    review = open_compliance_review(ctx["box_id"], "ROSTER_ANOMALY", "co-1")
    suspend_compliance_review(review["id"], "co-1")
    ctx["item_id"] = item["id"]
    ctx["review_id"] = review["id"]
    return ctx


def test_the_suspension_gate_wins_when_both_global_gates_hold(api):
    """PRD §2.8: "**They are evaluated in the order given below, and the first gate whose
    condition holds wins; the loser's error is never returned for that request.**
    Concretely, the suspension gate is evaluated at rung 11 of the validation ladder and
    the Form 1583 gate at rungs 17, 18 and 19, so a request that trips both returns the
    suspension gate's error and never the Form 1583 gate's."
    PRD §2.8: "Its condition is that the target mailbox has `service_status` equal to
    `SUSPENDED`. When it holds and the operation is on the list below, the request is
    rejected with `ERR_BOX_SUSPENDED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/suspension_gate_preempts_form_1583_gate_by_gate_precedence
    """
    ctx = _setup_suspended_box_with_blocked_member()

    member = read_recipient(ctx["recipient_id"])
    assert member["release_eligibility"] == "BLOCKED", (
        "the Form 1583 gate must also be tripped by this request"
    )

    response = api.create_disposition(
        ctx["item_id"],
        disposition_payload("SHRED", mail_item_version(ctx["item_id"])),
        ctx["holder_headers"],
    )
    validate_error(response, ApiErrorId.ERR_BOX_SUSPENDED.value)


def test_clearing_the_review_lets_the_identical_request_through(api):
    """PRD §3.11: "Resolved as `CLEARED`, it moves the mailbox `SUSPENDED → ACTIVE` on
    the service axis, sets `suspended_reason` back to `NONE`, recomputes
    `release_gate_state`, moves the compliance axis `NON_COMPLIANT → COMPLIANT`, and
    returns every roster member of the mailbox whose `roster_status` is `SUSPENDED` to
    `AUTHORIZED` — each of which re-derives its own `release_eligibility` and bumps its
    `version` by one, dragging pieces from `AWAITING_CLEARANCE` back into `HELD`
    wherever all five clauses now pass."
    PRD §2.8: "`OPEN` in every other case, which is to say when `service_status` is
    `ACTIVE` or `CLOSING`."

    Design: Difficulty/priority_pair_validation_conflict/suspension_gate_preempts_form_1583_gate_by_gate_precedence
    """
    ctx = _setup_suspended_box_with_blocked_member()

    resolve_compliance_review(ctx["review_id"], "CLEARED", "co-2")

    box = validate_success(api.get_box(ctx["box_id"], CMRA_OPERATOR))
    assert box["service_status"] == "ACTIVE"
    assert box["compliance_status"] == "COMPLIANT"
    assert box["release_gate_state"] == "OPEN"
    assert read_recipient(ctx["recipient_id"])["roster_status"] == "AUTHORIZED"
    assert read_mail_item(ctx["item_id"])["handling_status"] == "HELD"

    response = api.create_disposition(
        ctx["item_id"],
        disposition_payload("SHRED", mail_item_version(ctx["item_id"])),
        ctx["holder_headers"],
    )
    lodged = validate_success(response, 201)
    assert lodged["status"] == "PENDING"


# ==========================================================================
# Segregation of duties on resolution
# ==========================================================================
def test_the_officer_who_opened_a_review_may_not_resolve_it(api):
    """PRD §3.11: "**Resolution** closes a review and is where segregation of duties
    bites: the acting `X-User-ID` must differ from the review's `opened_by_user_id`, on
    pain of `ERR_UNAUTHORIZED`."
    PRD §3.11: "A review still in `OPEN` — one that never suspended the mailbox — may be
    resolved only as `CLEARED`, which moves the mailbox's compliance axis
    `UNDER_REVIEW → COMPLIANT` and leaves the service axis alone."

    Design: Corner/validations/compliance_officer_cannot_resolve_a_review_it_opened
    """
    ctx = setup_releasable_box("Z-3003", "Cal Duty", holder_email="cal@example.com")
    review = open_compliance_review(ctx["box_id"], "USPS_AUDIT", "co-1")

    self_resolve = api.resolve_compliance_review(
        review["id"], {"resolution": "CLEARED"}, make_compliance_officer_headers("co-1")
    )
    validate_error(self_resolve, ApiErrorId.ERR_UNAUTHORIZED.value)

    resolved = validate_success(
        api.resolve_compliance_review(
            review["id"], {"resolution": "CLEARED"}, make_compliance_officer_headers("co-2")
        )
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["opened_by_user_id"] == "co-1"
    assert resolved["resolved_by_user_id"] == "co-2"
    assert validate_success(api.get_box(ctx["box_id"], CMRA_OPERATOR))["compliance_status"] == (
        "COMPLIANT"
    )
