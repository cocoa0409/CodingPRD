"""Authorization-request lifecycle: state transitions, SLA computation,
partial/full approval, evidence-gated submit, the PEND->resume revision loop,
and SLA boundary precision.

Translates queue A (combinatorial_formula, non_linear_state_machine,
boundary_precision_check, compensating_invariant) and queue B (state_machines,
calculations) instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    register_actors,
    set_clock,
    create_draft_request,
    add_evidence,
    create_submitted_request,
    create_under_review_request,
    create_pended_request,
    create_approved_request,
    render_decision,
    make_provider_headers,
    make_payer_headers,
)


# --------------------------------------------------------------------------
# SLA computation — combinatorial_formula (queue A)
# --------------------------------------------------------------------------

def test_sla_due_at_expedited_branch(api):
    """PRD §3.4: "The base allowance is the payer's `expedited_sla_hours` when the
    request's `is_expedited` flag is true, and the payer's `standard_sla_hours`
    when it is false; the expedited default is 72 hours and the standard default
    is 168 hours. The deadline `sla_due_at` is then `review_started_at` advanced
    by the sum of that base allowance and the accumulated `clock_paused_hours`".

    Design: Difficulty/combinatorial_formula/sla_due_at_expedited_branch_with_inputs
    """
    actors = register_actors(
        payer_overrides={"standard_sla_hours": 168, "expedited_sla_hours": 72},
        provider_overrides={"specialty": "ONCOLOGY"},
        with_reviewer=False,
    )
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-100",
                           "requested_units": 1, "unit_cost_cents": 5000, "is_expedited": True},
    )
    assert ur["sla_due_at"] == "2026-06-04T00:00:00Z", (
        f"72h after 2026-06-01 expedited; got {ur['sla_due_at']}"
    )


def test_sla_due_at_standard_branch(api):
    """PRD §3.4: "The base allowance is the payer's `expedited_sla_hours` when the
    request's `is_expedited` flag is true, and the payer's `standard_sla_hours`
    when it is false; the expedited default is 72 hours and the standard default
    is 168 hours. The deadline `sla_due_at` is then `review_started_at` advanced
    by the sum of that base allowance and the accumulated `clock_paused_hours`".

    Design: Difficulty/combinatorial_formula/sla_due_at_expedited_branch_with_inputs
    """
    actors = register_actors(
        payer_overrides={"standard_sla_hours": 168, "expedited_sla_hours": 72},
        with_reviewer=False,
    )
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-100",
                           "requested_units": 1, "unit_cost_cents": 5000, "is_expedited": False},
    )
    assert ur["sla_due_at"] == "2026-06-08T00:00:00Z", (
        f"168h after 2026-06-01 standard; got {ur['sla_due_at']}"
    )


# --------------------------------------------------------------------------
# member_cost_share rounding — combinatorial_formula (queue A)
# --------------------------------------------------------------------------

def test_cost_share_round_per_line_then_sum(api):
    """PRD §2.8: "this rounding is applied per line item before any summation —
    never sum-then-round. The procedure component and each individual evidence
    line are each rounded to a whole cent first, and only the already-rounded
    whole-cent results are added together." PRD §3.5: "for each `ClinicalEvidence`
    row attached to the request ... the system multiplies that line's
    `line_item_cost_cents` by the member's `coinsurance_rate`, rounds each line
    half up to a whole cent, and sums those rounded line amounts."

    Design: Difficulty/combinatorial_formula/cost_share_round_per_line_then_sum
    """
    actors = register_actors(member_overrides={"coinsurance_rate": 0.2},
                             provider_overrides={"specialty": "RADIOLOGY"},
                             with_reviewer=False)
    set_clock("2026-06-01T00:00:00Z", make_provider_headers(actors["provider"]["id"]))
    req = create_draft_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-X",
                           "requested_units": 1, "unit_cost_cents": 0},
    )
    add_evidence(actors, req["id"], {"document_type": "IMAGING", "line_item_cost_cents": 1002, "uri": "s3://img1"})
    add_evidence(actors, req["id"], {"document_type": "IMAGING", "line_item_cost_cents": 1002, "uri": "s3://img2"})
    submitted = get_success_data(
        api.submit_request(req["id"], make_provider_headers(actors["provider"]["id"]))
    )
    assert submitted["member_cost_share_cents"] == 400, (
        f"round(1002*0.2)=200 per line, 200+200=400; got {submitted['member_cost_share_cents']}"
    )
    assert submitted["member_cost_share_cents"] != 401, "must not be the sum-then-round result 401"


def test_cost_share_procedure_per_unit_round_then_multiply(api):
    """PRD §2.8: "Wherever the coinsurance computation multiplies a cent amount by
    the member's cost-share fraction, the product is rounded half up to the
    nearest whole cent. Crucially, this rounding is applied per line item before
    any summation — never sum-then-round." PRD §3.5: "the system multiplies the
    request's `unit_cost_cents` by the member's `coinsurance_rate`, rounds that
    single-unit product half up to a whole cent, and then multiplies the rounded
    per-unit share by the effective number of units."

    Design: Difficulty/combinatorial_formula/cost_share_round_per_line_then_sum
    """
    actors = register_actors(member_overrides={"coinsurance_rate": 0.2},
                             provider_overrides={"specialty": "RADIOLOGY"},
                             with_reviewer=False)
    set_clock("2026-06-01T00:00:00Z", make_provider_headers(actors["provider"]["id"]))
    # unit_cost 1002 * 0.2 = 200.4 -> round half up = 200 per unit; * 3 units = 600.
    submitted = create_submitted_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-Y",
                           "requested_units": 3, "unit_cost_cents": 1002},
        evidence_overrides={"document_type": "IMAGING", "line_item_cost_cents": 0, "uri": "s3://y"},
    )
    assert submitted["member_cost_share_cents"] == 600, (
        f"round(1002*0.2)=200 per unit * 3 units = 600; got {submitted['member_cost_share_cents']}"
    )


# --------------------------------------------------------------------------
# dual-variant cost share full vs partial — dual_variant_calc (queue A)
# --------------------------------------------------------------------------

def test_cost_share_partial_approval_on_request(api):
    """PRD §3.3: "For a partial approval `approved_units` is required, must be at
    least 1, and must be strictly less than the request's `requested_units` ...
    the request's `approved_units` is set to the reduced count,
    `member_cost_share_cents` is recomputed from that smaller count". PRD §3.5:
    "the system multiplies the request's `unit_cost_cents` by the member's
    `coinsurance_rate`, rounds that single-unit product half up to a whole cent,
    and then multiplies the rounded per-unit share by the effective number of units."

    Design: Difficulty/dual_variant_calc/cost_share_full_vs_partial_approval_on_request
    """
    actors = register_actors(member_overrides={"coinsurance_rate": 0.2})
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "DRUG", "procedure_code": "NDC-001",
                           "requested_units": 4, "unit_cost_cents": 10000},
    )
    get_success_data(
        render_decision(actors, ur["id"], "PARTIAL", approved_units=2, rationale="Half medically necessary")
    )
    data = get_success_data(
        api.get_authorization_request(ur["id"], make_provider_headers(actors["provider"]["id"]))
    )
    assert data["approved_units"] == 2, f"expected 2, got {data['approved_units']}"
    assert data["member_cost_share_cents"] == 4000, (
        f"round(10000*0.2)=2000 per unit * 2 units; got {data['member_cost_share_cents']}"
    )


def test_cost_share_full_approval_on_request(api):
    """PRD §3.3: "An `APPROVE` outcome moves the request to `APPROVED`. The
    `approved_units` is forced to equal the request's `requested_units` (any
    supplied value is ignored for full approval). The decision creates the
    `ReviewDecision` row, sets the request's `approved_units` accordingly,
    recomputes `member_cost_share_cents` using the approved units". PRD §3.5:
    "the system multiplies the request's `unit_cost_cents` by the member's
    `coinsurance_rate`, rounds that single-unit product half up to a whole cent,
    and then multiplies the rounded per-unit share by the effective number of units."

    Design: Difficulty/dual_variant_calc/cost_share_full_vs_partial_approval_on_request
    """
    actors = register_actors(member_overrides={"coinsurance_rate": 0.2})
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    approved = create_approved_request(
        actors,
        request_overrides={"request_type": "DRUG", "procedure_code": "NDC-001",
                           "requested_units": 4, "unit_cost_cents": 10000},
        approved_units=4,
        outcome="APPROVE",
    )
    assert approved["approved_units"] == 4, f"expected 4, got {approved['approved_units']}"
    assert approved["member_cost_share_cents"] == 8000, (
        f"round(10000*0.2)=2000 per unit * 4 units; got {approved['member_cost_share_cents']}"
    )


# --------------------------------------------------------------------------
# approved_units variant selection — queue B (calculations)
# --------------------------------------------------------------------------

def test_partial_approval_variant_selection_caps_units(api):
    """PRD §3.3: "A `PARTIAL` outcome also moves the request to `APPROVED`, but
    the reviewer's supplied `approved_units` is honored. For a partial approval
    `approved_units` is required, must be at least 1, and must be strictly less
    than the request's `requested_units`".

    Design: Corner/calculations/partial_approval_variant_selection_caps_units
    """
    actors = register_actors()
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "DRUG", "procedure_code": "NDC-1",
                           "requested_units": 5, "unit_cost_cents": 5000},
    )
    get_success_data(render_decision(actors, ur["id"], "PARTIAL", approved_units=2, rationale="partial"))
    data = get_success_data(
        api.get_authorization_request(ur["id"], make_provider_headers(actors["provider"]["id"]))
    )
    assert data["approved_units"] == 2, f"PARTIAL honors supplied 2, got {data['approved_units']}"
    assert data["status"] == "APPROVED", f"PARTIAL moves to APPROVED, got {data['status']}"


# --------------------------------------------------------------------------
# non-linear state machine: PEND -> resume revision loop (queue A)
# --------------------------------------------------------------------------

def test_request_pended_to_under_review_revision_loop(api):
    """PRD §3.3: "A `PEND` outcome moves the request to `PENDED`." PRD §3.3:
    "Resuming moves the request from `PENDED` back to `UNDER_REVIEW`; the acting
    payer's `id` must equal the request's `payer_id`, and at least one new
    `ClinicalEvidence` row must have been added for the request after the pend
    decision was recorded."

    Design: Difficulty/non_linear_state_machine/request_pended_to_under_review_revision_loop
    """
    actors = register_actors(provider_overrides={"specialty": "NEUROLOGY"},
                             reviewer_overrides={"specialty": "NEUROLOGY"})
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    pended = create_pended_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-N",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    assert pended["status"] == "PENDED"
    # add new evidence after the pend decision, then resume
    add_evidence(actors, pended["id"], {"document_type": "LAB_RESULT", "line_item_cost_cents": 0, "uri": "s3://lab1"})
    resp = api.resume_review(pended["id"], make_payer_headers(actors["payer"]["id"]))
    data = validate_success(resp)
    assert data["status"] == "UNDER_REVIEW", (
        f"resume returns request to a previously-visited UNDER_REVIEW, got {data['status']}"
    )


def test_pend_decision_moves_request_to_pended(api):
    """PRD §3.3: "A `PEND` outcome moves the request to `PENDED`. A `pend_reason`
    of `INSUFFICIENT_EVIDENCE`, `MISSING_LMN`, or `PEER_TO_PEER_REQUIRED` is
    required. ... While the request sits in `PENDED` its SLA clock is paused".

    Design: Difficulty/non_linear_state_machine/request_pended_to_under_review_revision_loop
    """
    actors = register_actors(provider_overrides={"specialty": "NEUROLOGY"},
                             reviewer_overrides={"specialty": "NEUROLOGY"})
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    pended = create_pended_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-N2",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    assert pended["status"] == "PENDED", (
        f"PEND decision drives request to PENDED, got {pended['status']}"
    )


# --------------------------------------------------------------------------
# compensating invariant: PEND->resume conserves clock_paused_hours (queue A)
# --------------------------------------------------------------------------

def test_pend_then_resume_conserves_clock_paused_hours_ledger(api):
    """PRD §3.3: "Resuming adds the hours elapsed since pending began to
    `clock_paused_hours`, resets `review_started_at` to the current clock,
    recomputes `sla_due_at` so it now reflects the larger `clock_paused_hours`".
    PRD §3.4: "The deadline `sla_due_at` is then `review_started_at` advanced by
    the sum of that base allowance and the accumulated `clock_paused_hours`".

    Design: Difficulty/compensating_invariant/pend_then_resume_conserves_clock_paused_hours_ledger
    """
    actors = register_actors(
        payer_overrides={"standard_sla_hours": 168, "expedited_sla_hours": 72},
        provider_overrides={"specialty": "NEUROLOGY"},
        reviewer_overrides={"specialty": "NEUROLOGY"},
    )
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-PAUSE",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    set_clock("2026-06-02T00:00:00Z", payer_h)
    get_success_data(render_decision(actors, ur["id"], "PEND", pend_reason="INSUFFICIENT_EVIDENCE"))
    add_evidence(actors, ur["id"], {"document_type": "LAB_RESULT", "line_item_cost_cents": 0, "uri": "s3://pz2"})
    set_clock("2026-06-03T00:00:00Z", payer_h)
    resumed = get_success_data(api.resume_review(ur["id"], payer_h))
    assert resumed["clock_paused_hours"] == 24, (
        f"24h pause (06-02 to 06-03); got {resumed['clock_paused_hours']}"
    )
    assert resumed["sla_due_at"] == "2026-06-11T00:00:00Z", (
        f"review_started 2026-06-03 + 168h + 24h pause; got {resumed['sla_due_at']}"
    )


def test_pend_then_resume_credits_exact_48h_pause(api):
    """PRD §3.3: "Resuming adds the hours elapsed since pending began to
    `clock_paused_hours`, resets `review_started_at` to the current clock,
    recomputes `sla_due_at` so it now reflects the larger `clock_paused_hours`".
    PRD §3.4: "The deadline `sla_due_at` is then `review_started_at` advanced by
    the sum of that base allowance and the accumulated `clock_paused_hours`".

    Design: Difficulty/compensating_invariant/pend_then_resume_conserves_clock_paused_hours_ledger
    """
    actors = register_actors(
        payer_overrides={"standard_sla_hours": 168, "expedited_sla_hours": 72},
        provider_overrides={"specialty": "NEUROLOGY"},
        reviewer_overrides={"specialty": "NEUROLOGY"},
    )
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-PAUSE2",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    set_clock("2026-06-02T00:00:00Z", payer_h)
    get_success_data(render_decision(actors, ur["id"], "PEND", pend_reason="INSUFFICIENT_EVIDENCE"))
    add_evidence(actors, ur["id"], {"document_type": "LAB_RESULT", "line_item_cost_cents": 0, "uri": "s3://pz3"})
    # resume two days after pend began: 48h credited.
    set_clock("2026-06-04T00:00:00Z", payer_h)
    resumed = get_success_data(api.resume_review(ur["id"], payer_h))
    assert resumed["clock_paused_hours"] == 48, (
        f"48h pause (06-02 to 06-04); got {resumed['clock_paused_hours']}"
    )
    assert resumed["sla_due_at"] == "2026-06-13T00:00:00Z", (
        f"review_started 2026-06-04 + 168h + 48h pause; got {resumed['sla_due_at']}"
    )


# --------------------------------------------------------------------------
# boundary precision: review decision exactly at sla_due_at (queue A)
# --------------------------------------------------------------------------

def test_review_decision_exactly_at_sla_due_at_passes(api):
    """PRD §2.9: "Both clocks are enforced as hard deadlines: a review or appeal
    decision rendered after its respective deadline is rejected." PRD §3.6: "A
    review or appeal decision rendered after its deadline — past `sla_due_at` for
    a review decision, or past `appeal_deadline_at` for an appeal decision — is
    rejected with `ERR_PAST_DEADLINE` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/review_decision_exactly_at_sla_due_at_passes
    """
    actors = register_actors(
        payer_overrides={"standard_sla_hours": 168, "expedited_sla_hours": 72},
        provider_overrides={"specialty": "NEUROLOGY"},
        reviewer_overrides={"specialty": "NEUROLOGY"},
    )
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-B",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    assert ur["sla_due_at"] == "2026-06-08T00:00:00Z"
    set_clock("2026-06-08T00:00:00Z", payer_h)
    resp = api.create_review_decision(
        {"request_id": ur["id"], "reviewer_id": actors["reviewer"]["id"],
         "outcome": "APPROVE", "approved_units": 1, "rationale": "OK at boundary"},
        payer_h,
    )
    data = validate_success(resp, expected_status=201)
    fetched = get_success_data(api.get_authorization_request(ur["id"], payer_h))
    assert fetched["status"] == "APPROVED", "decision exactly AT sla_due_at must pass"


def test_review_decision_past_sla_due_at_rejected(api):
    """PRD §3.6: "A review or appeal decision rendered after its deadline — past
    `sla_due_at` for a review decision, or past `appeal_deadline_at` for an appeal
    decision — is rejected with `ERR_PAST_DEADLINE` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/review_decision_exactly_at_sla_due_at_passes
    """
    actors = register_actors(
        payer_overrides={"standard_sla_hours": 168, "expedited_sla_hours": 72},
        provider_overrides={"specialty": "NEUROLOGY"},
        reviewer_overrides={"specialty": "NEUROLOGY"},
    )
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-B",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    assert ur["sla_due_at"] == "2026-06-08T00:00:00Z"
    set_clock("2026-06-08T00:00:00.001Z", payer_h)
    resp = api.create_review_decision(
        {"request_id": ur["id"], "reviewer_id": actors["reviewer"]["id"],
         "outcome": "APPROVE", "approved_units": 1, "rationale": "late"},
        payer_h,
    )
    validate_error(resp, ApiErrorId.ERR_PAST_DEADLINE.value)


# --------------------------------------------------------------------------
# boundary precision: submit with zero evidence (queue A)
# --------------------------------------------------------------------------

def test_submit_with_zero_evidence_rejected(api):
    """PRD §3.2: "at least one `ClinicalEvidence` row must already exist for the
    request; an attempt to submit a request with zero evidence rows is rejected
    with `ERR_NO_EVIDENCE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/submit_with_zero_evidence_empty_set_boundary
    """
    actors = register_actors(provider_overrides={"specialty": "PRIMARY_CARE"}, with_reviewer=False)
    set_clock("2026-06-01T00:00:00Z", make_provider_headers(actors["provider"]["id"]))
    req = create_draft_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-E",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    resp = api.submit_request(req["id"], make_provider_headers(actors["provider"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_EVIDENCE.value)


def test_submit_with_one_evidence_succeeds(api):
    """PRD §3.2: "at least one `ClinicalEvidence` row must already exist for the
    request; an attempt to submit a request with zero evidence rows is rejected
    with `ERR_NO_EVIDENCE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/submit_with_zero_evidence_empty_set_boundary
    """
    actors = register_actors(provider_overrides={"specialty": "PRIMARY_CARE"}, with_reviewer=False)
    set_clock("2026-06-01T00:00:00Z", make_provider_headers(actors["provider"]["id"]))
    req = create_draft_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-E",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    add_evidence(actors, req["id"], {"document_type": "CHART_NOTE", "line_item_cost_cents": 0, "uri": "s3://e1"})
    resp = api.submit_request(req["id"], make_provider_headers(actors["provider"]["id"]))
    data = validate_success(resp)
    assert data["status"] == "SUBMITTED", f"submit with 1 evidence must succeed, got {data['status']}"


# --------------------------------------------------------------------------
# state-machine corner: invalid transitions / idempotency (queue B)
# --------------------------------------------------------------------------

def test_start_review_from_draft_invalid_state(api):
    """PRD §3.3: "The payer that owns a `SUBMITTED` request begins examining it,
    transitioning it from `SUBMITTED` to `UNDER_REVIEW`." PRD §3.9: "then whether
    the target resource is in a state from which the requested transition is
    defined (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/start_review_from_draft_invalid_state
    """
    actors = register_actors(provider_overrides={"specialty": "NEUROLOGY"}, with_reviewer=False)
    req = create_draft_request(
        actors, request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-1"}
    )
    resp = api.start_review(req["id"], make_payer_headers(actors["payer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_submit_twice_idempotency_second_fails(api):
    """PRD §3.2: "Submitting moves the request from `DRAFT` to `SUBMITTED`."
    PRD §3.9: "then whether the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/submit_twice_idempotency_second_fails
    """
    actors = register_actors(with_reviewer=False)
    set_clock("2026-06-01T00:00:00Z", make_provider_headers(actors["provider"]["id"]))
    submitted = create_submitted_request(
        actors,
        request_overrides={"request_type": "DRUG", "procedure_code": "NDC-1"},
        evidence_overrides={"document_type": "MEDICATION_HISTORY", "line_item_cost_cents": 0, "uri": "s3://e1"},
    )
    resp = api.submit_request(submitted["id"], make_provider_headers(actors["provider"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
