"""Form 1583, identification documents and the derived release-eligibility axis."""

from test_helpers import (
    CMRA_OPERATOR,
    COMPLIANCE_OFFICER,
    ApiErrorId,
    accept_form_1583,
    add_recipient,
    assert_form_1583,
    assert_id_document,
    assert_recipient,
    assert_usage_ledger_entry,
    file_and_verify_id_document,
    file_form_1583,
    log_and_match_letter,
    make_compliance_officer_headers,
    make_notary_headers,
    notarize_form_1583,
    open_billing_cycle,
    read_mail_item,
    read_recipient,
    set_clock,
    setup_releasable_box,
    validate_error,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# The five-hop clearance chain
# ==========================================================================
def test_accepting_a_form_authorizes_the_member_and_meters_one_recipient_unit(api):
    """PRD §3.3: "Acceptance sets `accepted_on` to the clock's calendar date,
    `accepted_by_user_id` to the acting `X-User-ID`, and `expires_on` to `accepted_on`
    plus 1,825 days — five years, the USPS validity period."
    PRD §3.3: "It also drives the roster axis `PENDING → AUTHORIZED`, meters one
    `RECIPIENT` unit, re-derives the member's own `release_eligibility`, and then —
    after that own re-derivation has settled — re-derives `release_eligibility` for
    every member whose `guarantor_recipient_id` points at this member."

    Design: Difficulty/transitive_cascade/form_1583_acceptance_five_hop_clearance_cascade
    """
    ctx = setup_releasable_box(
        "H-801", "Lee Wait", holder_email="lee@example.com", accept_form=False
    )
    item = log_and_match_letter(ctx)
    assert item["handling_status"] == "AWAITING_CLEARANCE"

    response = api.accept_form(ctx["form_id"], make_compliance_officer_headers("co-1"))
    form = validate_success(response)
    assert_form_1583(form)
    assert form["status"] == "ACCEPTED"
    assert form["accepted_on"] == "2026-05-01"
    assert form["expires_on"] == "2031-04-30"

    member = read_recipient(ctx["recipient_id"])
    assert member["roster_status"] == "AUTHORIZED"

    cycle = open_billing_cycle(ctx["box_id"])
    assert cycle["recipients_consumed"] == 1
    entries, meta = validate_paginated(
        api.list_cycle_usage_entries(
            cycle["id"], CMRA_OPERATOR, params={"unit_type": "RECIPIENT"}
        )
    )
    assert meta["total_count"] == 1
    entry = entries[0]
    assert_usage_ledger_entry(entry)
    assert entry["unit_type"] == "RECIPIENT"
    assert entry["tranche"] == "IN_TIER"
    assert entry["quantity"] == 1
    assert entry["unit_rate_cents"] == 0
    assert entry["amount_cents"] == 0
    assert entry["source_event"] == "RECIPIENT_AUTHORIZED"


def test_accepting_a_form_drags_the_members_piece_out_of_awaiting_clearance(api):
    """PRD §3.3: "Accepting a notarized form therefore runs a five-hop chain: the form
    moves `NOTARIZED → ACCEPTED`; because the form was accepted, the member's roster
    axis moves `PENDING → AUTHORIZED` and one `RECIPIENT` unit is metered; because the
    roster axis reached `AUTHORIZED`, the member's `release_eligibility` is re-derived
    and — if all five clauses now pass — moves `BLOCKED → RELEASABLE`; because the
    member became releasable, eligibility is re-derived for every member it guarantees;
    and because the member became releasable, every piece of theirs sitting in
    `AWAITING_CLEARANCE` moves to `HELD`."

    Design: Difficulty/transitive_cascade/form_1583_acceptance_five_hop_clearance_cascade
    """
    ctx = setup_releasable_box(
        "H-801", "Lee Wait", holder_email="lee@example.com", accept_form=False
    )
    item = log_and_match_letter(ctx)
    assert item["handling_status"] == "AWAITING_CLEARANCE"

    accept_form_1583(ctx["form_id"], "co-1")

    member = read_recipient(ctx["recipient_id"])
    assert_recipient(member)
    assert member["release_eligibility"] == "RELEASABLE"
    assert member["blocked_reason"] == "NONE"

    cleared = read_mail_item(item["id"])
    assert cleared["handling_status"] == "HELD"
    assert cleared["storage_status"] == "FREE_WINDOW"


def test_the_acceptance_response_already_carries_the_cascaded_state(api):
    """PRD §3.3: "Acceptance sets `accepted_on` to the clock's calendar date,
    `accepted_by_user_id` to the acting `X-User-ID`, and `expires_on` to `accepted_on`
    plus 1,825 days — five years, the USPS validity period."
    PRD §3.3: "When all five pass, the member is `RELEASABLE` and `blocked_reason` is
    `NONE`."

    Design: Corner/consistency_model/cascaded_changes_are_visible_in_the_triggering_response
    """
    ctx = setup_releasable_box(
        "Z-8001", "Gus Now", holder_email="gus@example.com", accept_form=False
    )

    form = validate_success(
        api.accept_form(ctx["form_id"], make_compliance_officer_headers("co-1"))
    )
    assert form["status"] == "ACCEPTED"
    assert form["expires_on"] == "2031-04-30"

    member = validate_success(api.get_recipient(ctx["recipient_id"], CMRA_OPERATOR))
    assert member["roster_status"] == "AUTHORIZED"
    assert member["release_eligibility"] == "RELEASABLE"
    assert validate_success(api.get_box(ctx["box_id"], CMRA_OPERATOR))[
        "roster_authorized_count"
    ] == 1


def test_recipient_usage_entry_is_append_only(api):
    """PRD §2.4: "Three resource types deliberately do not: a plan tier, a carrier rule
    and a usage-ledger entry carry only `id` and `created_at`, and their JSON bodies
    contain neither `updated_at` nor `version`."
    PRD §3.12: "Each entry records the `billing_cycle_id` of the open cycle the
    consumption was metered into, a nullable `mail_item_id` naming the piece the
    consumption is attributable to, a `unit_type` of `SCAN_PAGE`, `FORWARD`,
    `STORAGE_DAY` or `RECIPIENT`, a `tranche` of `IN_TIER` or `OVERAGE`, a `quantity` of
    at least 1, a `unit_rate_cents` which is always 0 when the tranche is `IN_TIER`, an
    `amount_cents` equal to `quantity` multiplied by `unit_rate_cents`, and a
    `source_event` of `SCAN_COMPLETED`, `FORWARD_SHIPPED`, `STORAGE_ACCRUAL`,
    `RECIPIENT_AUTHORIZED` or `PLAN_CHANGE`."

    Design: Corner/entities/usage_ledger_entry_is_append_only_without_version
    """
    ctx = setup_releasable_box("Z-0006", "Dee Ledger", holder_email="dee@example.com")
    cycle = open_billing_cycle(ctx["box_id"])

    entries, meta = validate_paginated(
        api.list_cycle_usage_entries(cycle["id"], CMRA_OPERATOR)
    )
    assert meta["total_count"] == 1
    entry = entries[0]
    assert entry["unit_type"] == "RECIPIENT"
    assert entry["tranche"] == "IN_TIER"
    assert entry["quantity"] == 1
    assert entry["unit_rate_cents"] == 0
    assert entry["amount_cents"] == 0
    assert "version" not in entry
    assert "updated_at" not in entry
    assert_usage_ledger_entry(entry)


# ==========================================================================
# Form lifecycle
# ==========================================================================
def test_notarizing_an_already_accepted_form_is_an_invalid_transition(api):
    """PRD §3.3: "A `Notary` — and only a `Notary` — witnesses the signature, moving the
    form `DRAFT → NOTARIZED`, which stamps `notarized_at` with the current
    logical-clock instant, records the acting `X-User-ID` as `notary_user_id`, and bumps
    `Form1583.version` by one."
    PRD §2.9 rung 14: "The target resource sits in a state from which the requested
    transition is declared. Otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/notarizing_an_accepted_form_is_an_invalid_transition
    """
    ctx = setup_releasable_box("Z-1003", "Kim Form", holder_email="kim@example.com")

    response = api.notarize_form(ctx["form_id"], make_notary_headers("not-9"))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    form = validate_success(api.get_form_1583(ctx["form_id"], COMPLIANCE_OFFICER))
    assert form["status"] == "ACCEPTED"
    assert form["notary_user_id"] == "not-1"


def test_rejecting_a_form_without_a_reason_is_a_validation_failure(api):
    """PRD §3.3: "Rejection, also a `ComplianceOfficer` act on a `NOTARIZED` form,
    requires a `rejection_reason` drawn from `ADDRESS_MISMATCH`, `ILLEGIBLE`,
    `NAME_MISMATCH` and `INCOMPLETE_ID`, moves the form to `REJECTED`, and bumps its
    version by one."
    PRD §2.9 rung 9: "Every required body field is present, carries the declared type,
    and sits inside its declared numeric range."

    Design: Corner/state_machines/rejecting_a_form_without_a_reason_is_rejected
    """
    ctx = setup_releasable_box(
        "Z-1004", "Lou Reason", holder_email="lou@example.com", accept_form=False
    )

    response = api.reject_form(ctx["form_id"], {}, COMPLIANCE_OFFICER)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    form = validate_success(api.get_form_1583(ctx["form_id"], COMPLIANCE_OFFICER))
    assert form["status"] == "NOTARIZED"
    assert form.get("rejection_reason") is None


def test_the_form_acceptor_may_not_be_the_notary(api):
    """PRD §2.1: "A `ComplianceOfficer` whose `X-User-ID` equals the review's
    `opened_by_user_id` may not resolve that review, and a `ComplianceOfficer` whose
    `X-User-ID` equals a form's `notary_user_id` may not accept that form."
    PRD §2.9 rung 15: "The acting `X-User-ID` differs from the review's
    `opened_by_user_id` when resolving, and from the form's `notary_user_id` when
    accepting. Otherwise `ERR_UNAUTHORIZED` (403)."

    Design: Corner/validations/form_acceptor_may_not_be_the_notary
    """
    ctx = setup_releasable_box(
        "Z-3004", "Del Notary", holder_email="del@example.com", accept_form=False
    )

    self_accept = api.accept_form(ctx["form_id"], make_compliance_officer_headers("not-1"))
    validate_error(self_accept, ApiErrorId.ERR_UNAUTHORIZED.value)

    form = validate_success(
        api.accept_form(ctx["form_id"], make_compliance_officer_headers("co-1"))
    )
    assert form["status"] == "ACCEPTED"
    assert form["accepted_by_user_id"] == "co-1"
    assert read_recipient(ctx["recipient_id"])["roster_status"] == "AUTHORIZED"


# ==========================================================================
# Identification documents and the re-entrant eligibility axis
# ==========================================================================
def test_photo_document_expiry_pushes_the_piece_back_to_awaiting_clearance(api):
    """PRD §3.3: "Whenever the clock advances, a document in `VERIFIED` or in
    `PENDING_REVIEW` whose `expires_on` is **strictly less than** the clock date — the
    expiry grace period is zero days, so there is no slack at all — moves to `EXPIRED`
    and bumps its `version` by one; expiry from `VERIFIED` additionally re-derives the
    owning member's eligibility, while expiry from `PENDING_REVIEW` has no such cascade
    because an unverified document never contributed to eligibility."
    PRD §3.3: "Crossing `RELEASABLE → BLOCKED` — which happens when any clause stops
    holding, whether through document expiry on a clock advance, form expiry, roster
    suspension or a guarantor becoming blocked — sets `blocked_reason` to the first
    failing clause, cascades every piece whose `matched_recipient_id` is this member and
    whose `handling_status` is `HELD` back into `AWAITING_CLEARANCE`, and bumps
    `Recipient.version` by one."

    Design: Difficulty/non_linear_state_machine/mail_item_held_awaiting_clearance_reentry_on_id_expiry
    """
    ctx = setup_releasable_box(
        "F-601", "Jo Lapse", holder_email="jo@example.com",
        photo_doc_type="DRIVERS_LICENSE", photo_expires_on="2026-05-10",
    )
    item = log_and_match_letter(ctx)
    assert item["handling_status"] == "HELD"

    set_clock("2026-05-11T00:00:00Z")

    assert read_mail_item(item["id"])["handling_status"] == "AWAITING_CLEARANCE"
    member = read_recipient(ctx["recipient_id"])
    assert member["release_eligibility"] == "BLOCKED"
    assert member["blocked_reason"] == "ID_EXPIRED"

    documents, _ = validate_paginated(
        api.list_id_documents(ctx["recipient_id"], CMRA_OPERATOR, params={"doc_class": "PHOTO"})
    )
    photo = next(d for d in documents if d["id"] == ctx["photo_document_id"])
    assert photo["status"] == "EXPIRED"


def test_verifying_a_fresh_photo_document_drags_the_piece_back_into_held(api):
    """PRD §3.3: "The axis is re-entrant in both directions: verifying a fresh address
    document after the previous one expired takes a member from `BLOCKED` to
    `RELEASABLE` again, dragging its pieces from `AWAITING_CLEARANCE` back to `HELD`
    with them."
    PRD §3.3: "For a member and a class `D`, the *governing* document of class `D` is
    chosen among that member's documents of `doc_class` `D` whose status is `VERIFIED`
    **or** `EXPIRED` — deliberately including expired rows — taking the one with the
    greatest `verified_at`, with ties broken by `created_at` ascending."

    Design: Difficulty/non_linear_state_machine/mail_item_held_awaiting_clearance_reentry_on_id_expiry
    """
    ctx = setup_releasable_box(
        "F-601", "Jo Lapse", holder_email="jo@example.com",
        photo_doc_type="DRIVERS_LICENSE", photo_expires_on="2026-05-10",
    )
    item = log_and_match_letter(ctx)
    set_clock("2026-05-11T00:00:00Z")

    replacement = file_and_verify_id_document(
        ctx["recipient_id"], "PHOTO", "PASSPORT", "2027-01-31"
    )

    member = read_recipient(ctx["recipient_id"])
    assert member["release_eligibility"] == "RELEASABLE"
    assert member["blocked_reason"] == "NONE"
    assert read_mail_item(item["id"])["handling_status"] == "HELD"

    documents, _ = validate_paginated(
        api.list_id_documents(ctx["recipient_id"], CMRA_OPERATOR, params={"doc_class": "PHOTO"})
    )
    by_id = {d["id"]: d for d in documents}
    assert by_id[ctx["photo_document_id"]]["status"] == "EXPIRED"
    assert by_id[replacement["id"]]["status"] == "VERIFIED"
    assert_id_document(by_id[replacement["id"]])


def test_an_expired_document_stays_expired_when_the_clock_is_wound_back(api):
    """PRD §3.3: "Once a document is `EXPIRED` or `SUPERSEDED`, that status is final and
    never changes again, not even if the clock is subsequently set backwards: a document
    expiring on 2026-06-30 is still `VERIFIED` on 2026-06-30, is `EXPIRED` on
    2026-07-01, and remains `EXPIRED` after the clock is moved back to 2026-06-15."
    PRD §3.3: "3. The governing `PHOTO` document has status `VERIFIED` and the governing
    `ADDRESS` document has status `VERIFIED`. Otherwise `BLOCKED` with `blocked_reason`
    `ID_EXPIRED`."

    Design: Corner/calculations/expired_id_document_never_returns_to_verified_on_clock_rollback
    """
    ctx = setup_releasable_box(
        "Z-2007", "Yan Monot", holder_email="yan@example.com",
        photo_expires_on="2026-05-10",
    )

    set_clock("2026-05-11T00:00:00Z")
    documents, _ = validate_paginated(
        api.list_id_documents(ctx["recipient_id"], CMRA_OPERATOR, params={"doc_class": "PHOTO"})
    )
    assert documents[0]["status"] == "EXPIRED"

    set_clock("2026-05-05T00:00:00Z")
    documents, _ = validate_paginated(
        api.list_id_documents(ctx["recipient_id"], CMRA_OPERATOR, params={"doc_class": "PHOTO"})
    )
    assert documents[0]["status"] == "EXPIRED"

    member = read_recipient(ctx["recipient_id"])
    assert member["release_eligibility"] == "BLOCKED"
    assert member["blocked_reason"] == "ID_EXPIRED"


# ==========================================================================
# The guarantor clause
# ==========================================================================
def _setup_guarantor_and_minor():
    """Guarantor G with a notarized-but-unaccepted form; minor M fully accepted."""
    ctx = setup_releasable_box(
        "Q-1701",
        "Pat Guard",
        holder_email="pat@example.com",
        photo_doc_type="DRIVERS_LICENSE",
        address_doc_type="LEASE",
        home_address_line="6 Guard Rd",
        accept_form=False,
    )
    minor = add_recipient(
        ctx["box_id"],
        "Quin Minor",
        recipient_kind="MINOR",
        guarantor_recipient_id=ctx["recipient_id"],
    )
    file_and_verify_id_document(minor["id"], "PHOTO", "STATE_ID", "2027-06-30")
    file_and_verify_id_document(minor["id"], "ADDRESS", "UTILITY_BILL", "2027-03-31")
    minor_form = file_form_1583(minor["id"], "6 Guard Rd")
    notarize_form_1583(minor_form["id"], "not-1")
    accept_form_1583(minor_form["id"], "co-1")
    ctx["minor"] = minor
    ctx["minor_id"] = minor["id"]
    ctx["minor_form_id"] = minor_form["id"]
    return ctx


def test_a_minor_with_a_blocked_guarantor_reports_guarantor_blocked(api):
    """PRD §3.3: "4. The member's `recipient_kind` is not `MINOR`, or else the guarantor
    member named by `guarantor_recipient_id` itself has `release_eligibility`
    `RELEASABLE`. Otherwise `BLOCKED` with `blocked_reason` `GUARANTOR_BLOCKED`."
    PRD §3.3: "The five clauses are evaluated **in this order, stopping at the first
    failure**, and `blocked_reason` reports the *first* failing clause, never the last:"

    Design: Difficulty/cross_entity_state_dependency/minor_recipient_release_gated_by_guarantor_recipient
    """
    ctx = _setup_guarantor_and_minor()

    minor = read_recipient(ctx["minor_id"])
    assert minor["roster_status"] == "AUTHORIZED"
    assert minor["release_eligibility"] == "BLOCKED"
    assert minor["blocked_reason"] == "GUARANTOR_BLOCKED"
    assert minor["guarantor_recipient_id"] == ctx["recipient_id"]


def test_clearing_the_guarantor_releases_the_minor_in_the_same_write(api):
    """PRD §3.3: "Crossing `BLOCKED → RELEASABLE` sets `blocked_reason` to `NONE`,
    re-derives eligibility for every member whose `guarantor_recipient_id` points at
    this member, cascades every piece whose `matched_recipient_id` is this member and
    whose `handling_status` is `AWAITING_CLEARANCE` into `HELD`, and bumps
    `Recipient.version` by one."
    PRD §3.3: "When all five pass, the member is `RELEASABLE` and `blocked_reason` is
    `NONE`."

    Design: Difficulty/cross_entity_state_dependency/minor_recipient_release_gated_by_guarantor_recipient
    """
    ctx = _setup_guarantor_and_minor()

    validate_success(api.accept_form(ctx["form_id"], make_compliance_officer_headers("co-1")))

    guarantor = read_recipient(ctx["recipient_id"])
    assert guarantor["release_eligibility"] == "RELEASABLE"

    minor = read_recipient(ctx["minor_id"])
    assert minor["release_eligibility"] == "RELEASABLE"
    assert minor["blocked_reason"] == "NONE"
