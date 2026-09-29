"""Corner cases on the state machines: initial states, terminal lockdown, idempotency.

Each test walks one lifecycle to a specific node and then pushes on an edge that
must not exist, or on an edge that must exist exactly once, and checks that the
refusal leaves every derived counter and every sibling row exactly where it was.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_election_payload,
    create_interim_extension,
    create_offer_payload,
    create_rights_dispute_payload,
    create_subscriber_report,
    execute_agreement_payload,
    make_compliance_officer_headers,
    make_group_counsel_headers,
    open_audit_finding,
    read_agreement,
    read_election,
    read_extensions,
    read_negotiation,
    read_offer,
    read_rights_disputes,
    read_settlements,
    read_station,
    read_subscriber_report,
    reject_offer_payload,
    resolve_audit_finding,
    resolve_audit_finding_payload,
    resolve_rights_dispute_payload,
    set_clock,
    setup_accepted_agreement,
    setup_draft_election,
    setup_executed_agreement,
    setup_issued_settlement,
    setup_open_negotiation,
    setup_station_and_distributor,
    setup_submitted_station_offer,
    validate_error,
    validate_paginated,
    validate_success,
    void_settlement_payload,
)

ADMIN = TEST_USERS["carriage_admin_headers"]


def test_new_election_is_draft_with_no_negotiation_row(api):
    """Creating an election mints no negotiation: filing is what opens one.

    PRD §3.3: "The new election's `status` begins at `DRAFT` and its `filed_at_utc`
    stays null until it is actually served."
    PRD §3.3: "Filing on this branch stamps `filed_at_utc` with the current logical
    clock, creates exactly one **Negotiation** whose `election_id` points back at the
    election, whose `status` starts at `OPEN` and whose `round_number` starts at 0,
    computes that negotiation's `blackout_notice_deadline_utc` as described in §3.6,
    and recomputes the station's `filed_election_count`."

    Design: Corner/state_machines/corner_election_starts_in_draft_with_no_negotiation
    """
    ctx = setup_station_and_distributor()

    response = api.create_election(
        create_election_payload(ctx["station"]["id"], ctx["distributor"]["id"]),
        ctx["negotiator_headers"],
    )
    election = validate_success(response, 201)

    assert election["status"] == "DRAFT"
    assert election["filed_at_utc"] is None

    negotiations, meta = validate_paginated(
        api.list_election_negotiations(election["id"], ADMIN)
    )
    assert meta["total_count"] == 0
    assert negotiations == []

    assert read_station(ctx["station"]["id"])["filed_election_count"] == 0


def test_filing_an_already_filed_election_is_refused_and_opens_no_second_negotiation(api):
    """Filing is not idempotent, and the refusal mints no second negotiation.

    PRD §2.8: "Election is in `DRAFT` - `ERR_ELECTION_NOT_DRAFT`. Applies to amending
    an election and filing an election."

    Design: Corner/state_machines/corner_file_already_filed_election_returns_election_not_draft
    """
    ctx = setup_open_negotiation()
    election_id = ctx["election"]["id"]
    assert ctx["election"]["status"] == "NEGOTIATING"

    response = api.file_election(election_id, {}, ctx["negotiator_headers"])
    validate_error(response, ApiErrorId.ERR_ELECTION_NOT_DRAFT.value, 409)

    assert read_election(election_id)["status"] == "NEGOTIATING"

    negotiations, meta = validate_paginated(
        api.list_election_negotiations(election_id, ADMIN)
    )
    assert meta["total_count"] == 1
    assert len(negotiations) == 1
    assert negotiations[0]["id"] == ctx["negotiation"]["id"]

    assert read_station(ctx["station"]["id"])["filed_election_count"] == 1


MUST_CARRY_ELECTION = {
    "election_type": "MUST_CARRY",
    "requested_tier": "EXPANDED_BASIC",
    "incumbent_rate_per_sub_cents": 0,
}


def test_must_carry_election_asking_for_expanded_basic_cannot_be_filed(api):
    """The must-carry branch is BROADCAST_BASIC only, so the filing is refused.

    PRD §3.3: "Must-carry carriage is compulsory, uncompensated, and available on
    `BROADCAST_BASIC` only, because negotiated tier placement exists exclusively on the
    retransmission-consent path; filing a must-carry election whose `requested_tier` is
    anything other than `BROADCAST_BASIC` is refused with
    `ERR_MUST_CARRY_NO_NEGOTIATION`."

    Design: Corner/state_machines/corner_must_carry_election_requesting_expanded_basic_is_refused
    """
    ctx = setup_draft_election(election=MUST_CARRY_ELECTION)
    election_id = ctx["election"]["id"]

    response = api.file_election(election_id, {}, ctx["negotiator_headers"])
    validate_error(response, ApiErrorId.ERR_MUST_CARRY_NO_NEGOTIATION.value, 422)

    election = read_election(election_id)
    assert election["status"] == "DRAFT"
    assert election["filed_at_utc"] is None
    assert read_station(ctx["station"]["id"])["filed_election_count"] == 0


def test_must_carry_election_amended_to_broadcast_basic_files_without_a_negotiation(api):
    """Once the tier is corrected the must-carry branch files and opens nothing.

    PRD §3.3: "This branch also stamps `filed_at_utc` and recomputes
    `filed_election_count`, but it creates no negotiation whatsoever - there is nothing
    to negotiate."

    Design: Corner/state_machines/corner_must_carry_election_requesting_expanded_basic_is_refused
    """
    ctx = setup_draft_election(election=MUST_CARRY_ELECTION)
    election_id = ctx["election"]["id"]
    validate_error(
        api.file_election(election_id, {}, ctx["negotiator_headers"]),
        ApiErrorId.ERR_MUST_CARRY_NO_NEGOTIATION.value,
        422,
    )

    amended = validate_success(
        api.amend_election(
            election_id,
            {"requested_tier": "BROADCAST_BASIC"},
            ctx["negotiator_headers"],
        ),
        200,
    )
    assert amended["requested_tier"] == "BROADCAST_BASIC"
    assert amended["status"] == "DRAFT"

    filed = validate_success(
        api.file_election(election_id, {}, ctx["negotiator_headers"]), 200
    )
    assert filed["status"] == "ELECTION_EFFECTIVE"
    assert filed["filed_at_utc"] == "2026-08-01T00:00:00Z"

    negotiations, meta = validate_paginated(
        api.list_election_negotiations(election_id, ADMIN)
    )
    assert meta["total_count"] == 0
    assert negotiations == []

    assert read_station(ctx["station"]["id"])["filed_election_count"] == 1


def test_rejecting_an_already_accepted_offer_is_refused(api):
    """ACCEPTED is terminal for an offer, so the counterparty can no longer reject it.

    PRD §2.8: "Offer is outstanding, meaning its status is `SUBMITTED` -
    `ERR_OFFER_NOT_OUTSTANDING`. Applies to accepting an offer and rejecting an offer."

    Design: Corner/state_machines/corner_reject_accepted_offer_returns_offer_not_outstanding
    """
    ctx = setup_accepted_agreement()
    offer_id = ctx["offer"]["id"]

    response = api.reject_offer(
        offer_id,
        reject_offer_payload(rejection_reason="Too late, already consented"),
        ctx["rep_headers"],
    )
    validate_error(response, ApiErrorId.ERR_OFFER_NOT_OUTSTANDING.value, 409)

    offer = read_offer(offer_id)
    assert offer["status"] == "ACCEPTED"
    assert offer["rejection_reason"] is None

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["execution_status"] == "PENDING_EXECUTION"


def test_offer_on_a_consented_negotiation_is_refused_and_moves_no_counter(api):
    """CONSENTED is terminal for a negotiation: no further round, no version bump.

    PRD §3.5: "A side attempting to speak out of turn, and any attempt to submit on a
    `CONSENTED` or `CANCELLED` negotiation, is refused with `ERR_NEGOTIATION_NOT_OPEN`."

    Design: Corner/state_machines/corner_offer_on_consented_negotiation_returns_negotiation_not_open
    """
    ctx = setup_accepted_agreement()
    negotiation_id = ctx["negotiation"]["id"]
    before = read_negotiation(negotiation_id)
    assert before["status"] == "CONSENTED"
    assert before["round_number"] == 1

    response = api.create_offer(
        negotiation_id,
        create_offer_payload(
            ctx["report"]["id"],
            base_rate_per_sub_cents=200,
            escalator_bp_per_year=400,
            term_months=24,
            tier="EXPANDED_BASIC",
            penetration_commitment_bp=4000,
            includes_digital_rights=False,
            includes_ooh_rights=False,
            includes_streaming_rights=False,
        ),
        ctx["rep_headers"],
    )
    validate_error(response, ApiErrorId.ERR_NEGOTIATION_NOT_OPEN.value, 409)

    after = read_negotiation(negotiation_id)
    assert after["status"] == "CONSENTED"
    assert after["round_number"] == 1
    assert after["station_offer_count"] == 1
    assert after["distributor_offer_count"] == 0
    assert after["version"] == before["version"]


def test_second_execution_of_an_executed_agreement_is_refused(api):
    """Execution is single-shot and the signing counsel of record is not overwritten.

    PRD §2.8: "Agreement is in the required execution phase -
    `ERR_AGREEMENT_NOT_PENDING_EXECUTION`. Applies to five operations."
    PRD §3.7: "Execution takes an `execution_note` and advances `PENDING_EXECUTION →
    EXECUTED`, stamping `executed_by_user_id` with the executing counsel's `X-User-ID`."

    Design: Corner/state_machines/corner_second_execute_returns_agreement_not_pending_execution
    """
    ctx = setup_executed_agreement()
    agreement_id = ctx["agreement"]["id"]
    assert ctx["agreement"]["executed_by_user_id"] == "counsel-2"

    response = api.execute_agreement(
        agreement_id,
        execute_agreement_payload(execution_note="Third counsel tries again"),
        make_group_counsel_headers("counsel-3"),
    )
    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_PENDING_EXECUTION.value, 409)

    agreement = read_agreement(agreement_id)
    assert agreement["execution_status"] == "EXECUTED"
    assert agreement["executed_by_user_id"] == "counsel-2"
    assert agreement["accepted_by_user_id"] == "counsel-1"


def test_resolving_an_already_substantiated_finding_does_not_apply_the_delta_twice(api):
    """SUBSTANTIATED is terminal, so the report's audit adjustment stays at one delta.

    PRD §2.8: "Audit finding is `OPEN` - `ERR_AUDIT_FINDING_NOT_OPEN`. Applies to
    resolving an audit finding."
    PRD §3.4: "At the second level the report recomputes `audit_adjustment_subscribers`
    as the sum of `adjustment_subscribers` over all findings on it whose status is
    `SUBSTANTIATED` - findings still `OPEN` and findings `DISMISSED` contribute nothing -
    and then recomputes `adjusted_subscriber_count` and `billable_subscriber_basis` under
    the audited variant."

    Design: Corner/state_machines/corner_resolve_already_substantiated_finding_returns_finding_not_open
    """
    ctx = setup_station_and_distributor(with_affiliation=False)
    report = create_subscriber_report(ctx["station"]["id"], ctx["distributor"]["id"])
    finding = open_audit_finding(
        report["id"], ctx["station"]["id"], adjustment_subscribers=6000
    )
    substantiated = resolve_audit_finding(finding["id"], "SUBSTANTIATED")
    assert substantiated["status"] == "SUBSTANTIATED"

    response = api.resolve_audit_finding(
        finding["id"],
        resolve_audit_finding_payload("SUBSTANTIATED", resolution_note="Second attempt"),
        make_compliance_officer_headers(),
    )
    validate_error(response, ApiErrorId.ERR_AUDIT_FINDING_NOT_OPEN.value, 409)

    findings, meta = validate_paginated(api.list_audit_findings(report["id"], ADMIN))
    assert meta["total_count"] == 1
    assert findings[0]["status"] == "SUBSTANTIATED"

    reread = read_subscriber_report(report["id"])
    assert reread["audit_adjustment_subscribers"] == 6000
    assert reread["billable_subscriber_basis"] == 106000
    assert reread["status"] == "ADJUSTED"


def _raise_digital_dispute(api):
    """An EXECUTED agreement granting DIGITAL and STREAMING, with a RAISED dispute."""
    ctx = setup_executed_agreement()
    assert sorted(ctx["agreement"]["granted_rights_scope"]) == ["DIGITAL", "STREAMING"]
    ctx["dispute"] = validate_success(
        api.create_rights_dispute(
            ctx["agreement"]["id"],
            create_rights_dispute_payload(
                "DIGITAL",
                claimed_definition="Simulcast on owned-and-operated apps only",
            ),
            ctx["rep_headers"],
        ),
        201,
    )
    return ctx


def _resolve_dispute(api, dispute_id, resolution, note):
    return api.resolve_rights_dispute(
        dispute_id,
        resolve_rights_dispute_payload(resolution, resolution_note=note),
        make_compliance_officer_headers(),
    )


def test_dispute_travels_through_mediation_to_included_without_touching_the_grant(api):
    """The mediation waypoint is real and an INCLUDED outcome costs the grant nothing.

    PRD §3.8: "A `MEDIATION` resolution advances `RAISED → IN_MEDIATION`, records the
    note, and changes nothing economically: `credit_bp_applied` stays 0 and the
    agreement's `granted_rights_scope` is untouched."
    PRD §3.8: "The station group's definition stands: `credit_bp_applied` stays 0,
    `granted_rights_scope` keeps the `disputed_term`, and no settlement is recomputed."

    Design: Corner/state_machines/corner_dispute_mediation_then_included_leaves_grant_intact
    """
    ctx = _raise_digital_dispute(api)
    dispute_id = ctx["dispute"]["id"]
    assert ctx["dispute"]["raised_by"] == "DISTRIBUTOR"
    assert ctx["dispute"]["status"] == "RAISED"

    mediated = validate_success(
        _resolve_dispute(
            api, dispute_id, "MEDIATION", "Referred to the FCC-supervised mediator"
        ),
        200,
    )
    assert mediated["status"] == "IN_MEDIATION"
    assert mediated["credit_bp_applied"] == 0

    included = validate_success(
        _resolve_dispute(
            api, dispute_id, "INCLUDED", "Mediator sustains the broad digital definition"
        ),
        200,
    )
    assert included["status"] == "RESOLVED_INCLUDED"
    assert included["credit_bp_applied"] == 0

    agreement = read_agreement(ctx["agreement"]["id"])
    assert sorted(agreement["granted_rights_scope"]) == ["DIGITAL", "STREAMING"]
    assert agreement["rights_credit_bp_total"] == 0


def test_resolving_a_settled_included_dispute_again_is_refused(api):
    """RESOLVED_INCLUDED is settled: it cannot be reopened as an exclusion.

    PRD §3.8: "Resolution requires the dispute to be in `RAISED` or `IN_MEDIATION`; a
    dispute already at `RESOLVED_INCLUDED` or `RESOLVED_EXCLUDED` is refused with
    `ERR_DISPUTE_NOT_PENDING`."

    Design: Corner/state_machines/corner_dispute_mediation_then_included_leaves_grant_intact
    """
    ctx = _raise_digital_dispute(api)
    dispute_id = ctx["dispute"]["id"]
    validate_success(
        _resolve_dispute(
            api, dispute_id, "MEDIATION", "Referred to the FCC-supervised mediator"
        ),
        200,
    )
    validate_success(
        _resolve_dispute(
            api, dispute_id, "INCLUDED", "Mediator sustains the broad digital definition"
        ),
        200,
    )

    response = _resolve_dispute(
        api, dispute_id, "EXCLUDED", "Attempt to reopen a settled dispute"
    )
    validate_error(response, ApiErrorId.ERR_DISPUTE_NOT_PENDING.value, 409)

    disputes = read_rights_disputes(ctx["agreement"]["id"])
    assert len(disputes) == 1
    assert disputes[0]["status"] == "RESOLVED_INCLUDED"
    assert disputes[0]["credit_bp_applied"] == 0

    agreement = read_agreement(ctx["agreement"]["id"])
    assert sorted(agreement["granted_rights_scope"]) == ["DIGITAL", "STREAMING"]
    assert agreement["rights_credit_bp_total"] == 0


def test_sweep_lapses_the_election_and_expires_the_offer_on_its_negotiation(api):
    """One sweep past the incumbent expiry runs the whole lapse cascade in one call.

    PRD §3.9: "Elections in `NEGOTIATING` whose `incumbent_expiry_utc` is at or before
    the clock, which have no carriage agreement on their negotiation and no `ACTIVE`
    interim extension covering the clock, move to `ELECTION_LAPSED` - cancelling their
    negotiation and expiring that negotiation's `SUBMITTED` offers, and additionally,
    where the negotiation was sitting at `IMPASSE`, cancelling it from there and expiring
    its outstanding offers just the same."

    Design: Corner/state_machines/corner_expiration_sweep_lapses_election_and_expires_its_offer
    """
    ctx = setup_submitted_station_offer()
    set_clock("2027-01-02T00:00:00Z")

    counts = validate_success(api.run_expiration_sweep({}, ADMIN), 200)
    assert counts["lapsed_election_count"] == 1
    assert counts["expired_agreement_count"] == 0

    assert read_election(ctx["election"]["id"])["status"] == "ELECTION_LAPSED"
    assert read_negotiation(ctx["negotiation"]["id"])["status"] == "CANCELLED"
    assert read_offer(ctx["offer"]["id"])["status"] == "EXPIRED"
    assert read_station(ctx["station"]["id"])["filed_election_count"] == 0
    assert read_subscriber_report(ctx["report"]["id"])["status"] == "REPORTED"


def test_one_sweep_expires_the_agreement_lapses_its_extension_and_accepts_the_report(api):
    """Every time-gated lifecycle advances in the same maintenance pass.

    PRD §3.9: "Carriage agreements in `EXECUTED` whose `effective_end_utc` is at or
    before the clock move to `EXPIRED`."
    PRD §3.9: "Interim extensions in `ACTIVE` whose `extension_end_utc` is at or before
    the clock move to `LAPSED`, leaving their days inside the extension budget."
    PRD §3.9: "Subscriber reports past their 180-day audit window with no finding still
    `OPEN` move to `ACCEPTED`."

    Design: Corner/state_machines/corner_sweep_expires_executed_agreement_and_lapses_its_extension
    """
    ctx = setup_executed_agreement()
    agreement_id = ctx["agreement"]["id"]
    extension = create_interim_extension(agreement_id, ctx["station"]["id"])
    assert extension["extension_end_utc"] == "2030-03-02T00:00:00Z"
    assert extension["status"] == "ACTIVE"

    set_clock("2030-04-03T00:00:00Z")
    counts = validate_success(api.run_expiration_sweep({}, ADMIN), 200)
    assert counts["expired_agreement_count"] == 1
    assert counts["lapsed_extension_count"] == 1
    assert counts["accepted_report_count"] == 1
    assert counts["expired_affiliation_count"] == 0

    agreement = read_agreement(agreement_id)
    assert agreement["execution_status"] == "EXPIRED"
    assert agreement["consumed_extension_days"] == 60

    extensions = read_extensions(agreement_id)
    assert [item["status"] for item in extensions] == ["LAPSED"]

    assert read_subscriber_report(ctx["report"]["id"])["status"] == "ACCEPTED"


def test_voiding_an_already_voided_settlement_does_not_double_reverse_the_ledger(api):
    """VOIDED is terminal, and the agreement's lifetime ledger never goes negative.

    PRD §3.9: "A `GroupCounsel` supplies a `void_reason`; the settlement may be in
    either `ISSUED` or `TRUED_UP`, and a `VOIDED` settlement accepts neither true-up nor
    a second void, both refused with `ERR_SETTLEMENT_NOT_ISSUED`."
    PRD §3.9: "Voiding moves `status` to `VOIDED`, and because the agreement's lifetime
    totals sum only over settlements in `ISSUED` or `TRUED_UP`, this row's amounts drop
    straight out of both `lifetime_gross_fee_cents` and `lifetime_net_retained_cents`,
    restoring the ledger to exactly the value it held before that settlement was issued."

    Design: Corner/state_machines/corner_void_already_voided_settlement_returns_settlement_not_issued
    """
    ctx = setup_issued_settlement()
    settlement_id = ctx["settlement"]["id"]
    assert ctx["settlement"]["issued_by_user_id"] == "counsel-1"

    voided = validate_success(
        api.void_fee_settlement(
            settlement_id,
            void_settlement_payload(),
            make_group_counsel_headers("counsel-2"),
        ),
        200,
    )
    assert voided["status"] == "VOIDED"

    response = api.void_fee_settlement(
        settlement_id,
        void_settlement_payload(void_reason="Second void attempt"),
        make_group_counsel_headers("counsel-3"),
    )
    validate_error(response, ApiErrorId.ERR_SETTLEMENT_NOT_ISSUED.value, 409)

    settlements = read_settlements(ctx["agreement"]["id"])
    assert [item["status"] for item in settlements] == ["VOIDED"]

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["lifetime_gross_fee_cents"] == 0
    assert agreement["lifetime_net_retained_cents"] == 0
