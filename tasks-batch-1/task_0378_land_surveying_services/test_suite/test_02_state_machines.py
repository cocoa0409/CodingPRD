"""State-machine behavior: the PlatDrawing revision cycle, the Invoice parallel
lifecycle/payment axes, invalid transitions, terminal-state lockdown, initial
states, and the research-packet title-hold re-open loop.

Difficulty queue: non_linear_state_machine.
Corner queue: state_machines section.
"""
from test_helpers import (
    fixtures as fx,
    make_billing_clerk_headers,
    make_coordinator_headers,
    make_drafter_headers,
    make_researcher_headers,
    make_surveyor_headers,
    create_research_packet_payload,
    create_survey_order_payload,
    payment_payload,
    seal_payload,
    validate_error,
    validate_success,
    ApiErrorId,
)


# ════════════════════════════════════════════════════════════════════════
# Difficulty/non_linear_state_machine/plat_revision_cycle_seal_to_in_revision_to_drafted
# ════════════════════════════════════════════════════════════════════════
def test_revision_apply_unseals_plat_then_resume_draft_returns_to_drafted(api):
    """PRD §3.5: "The plat moves from `SEALED` to `IN_REVISION`; its seal is cleared,
    setting `sealed_by_id` back to null and `sealed_at` back to null."
    PRD §3.5: "From `IN_REVISION` a `Drafter` resumes the draft, moving the plat from
    `IN_REVISION` back to `DRAFTED` for re-work."

    A SEALED plat, after a CLIENT_CHANGE revision is applied, is IN_REVISION with a
    null sealed_by_id; resume-draft then returns it to DRAFTED, and the order's
    revision_count is 1.

    Design: Difficulty/non_linear_state_machine/plat_revision_cycle_seal_to_in_revision_to_drafted
    """
    ctx = fx.sealed_plat(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    did = crew["drafter"]["id"]

    fx.apply_client_change_revision(ctx)
    plat = validate_success(
        api.get_plat_drawing(ctx["plat_id"], make_coordinator_headers(cid)), 200)
    assert plat["status"] == "IN_REVISION"
    assert plat["sealed_by_id"] is None

    resumed = validate_success(api.resume_draft(ctx["plat_id"], make_drafter_headers(did)), 200)
    assert resumed["status"] == "DRAFTED"

    order = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert order["revision_count"] == 1


def test_revision_cycle_reverts_order_to_drafting(api):
    """PRD §3.5: "the parent order reverts from `SEALED` back to `DRAFTING` so the
    plat can be re-drafted, re-reviewed, and re-sealed; reaching `SEALED` again
    requires sealing a plat anew."

    Applying a revision to the order's sealed plat reverts the order SEALED->DRAFTING,
    confirming the cyclic loop on the parent.

    Design: Difficulty/non_linear_state_machine/plat_revision_cycle_seal_to_in_revision_to_drafted
    """
    ctx = fx.sealed_plat(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]

    pre = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert pre["status"] == "SEALED"

    fx.apply_client_change_revision(ctx)
    order = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert order["status"] == "DRAFTING"


# ════════════════════════════════════════════════════════════════════════
# Difficulty/non_linear_state_machine/invoice_parallel_lifecycle_and_payment_axes
# ════════════════════════════════════════════════════════════════════════
def test_partial_payment_advances_payment_axis_only(api):
    """PRD §3.6: "If a payment leaves a positive balance, the invoice stays `ISSUED`
    and, on the first such partial payment, the `payment_status` advances from
    `UNPAID` to `PARTIAL` (the payment axis moving independently of the lifecycle
    axis)."

    A partial payment of 100000 against a 155880 invoice leaves balance 55880,
    payment_status PARTIAL, lifecycle_status still ISSUED.

    Design: Difficulty/non_linear_state_machine/invoice_parallel_lifecycle_and_payment_axes
    """
    ctx = fx.issued_invoice(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    bid = crew["billing"]["id"]

    updated = validate_success(
        api.pay_invoice(ctx["invoice_id"], payment_payload(100000),
                        make_billing_clerk_headers(bid)), 200)
    assert updated["payment_status"] == "PARTIAL"
    assert updated["lifecycle_status"] == "ISSUED"
    assert updated["balance_due_cents"] == 55880


def test_final_payment_closes_both_axes(api):
    """PRD §3.6: "If a payment brings `balance_due_cents` to exactly zero, the
    invoice's `lifecycle_status` moves from `ISSUED` to `CLOSED` and its
    `payment_status` becomes `PAID`."

    After a 100000 partial, a 55880 payment brings the balance to zero, advancing
    BOTH axes: lifecycle_status CLOSED and payment_status PAID.

    Design: Difficulty/non_linear_state_machine/invoice_parallel_lifecycle_and_payment_axes
    """
    ctx = fx.issued_invoice(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    bid = crew["billing"]["id"]

    validate_success(
        api.pay_invoice(ctx["invoice_id"], payment_payload(100000),
                        make_billing_clerk_headers(bid)), 200)
    final = validate_success(
        api.pay_invoice(ctx["invoice_id"], payment_payload(55880),
                        make_billing_clerk_headers(bid)), 200)
    assert final["payment_status"] == "PAID"
    assert final["lifecycle_status"] == "CLOSED"
    assert final["balance_due_cents"] == 0


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/start_research_from_research_returns_invalid_state
# ════════════════════════════════════════════════════════════════════════
def test_start_research_twice_returns_invalid_state(api):
    """PRD §3.1: "Advancing an order out of `INTAKE` into `RESEARCH` is a
    `Coordinator` action and is permitted only when exactly one `ResearchPacket`
    already exists for the order."
    PRD §2.9: "The state-machine legality of the requested transition
    (`ERR_INVALID_STATE`) is checked fifth, before any of the domain-specific
    business rules."

    Calling start-research a second time (order already RESEARCH) is not a defined
    transition from RESEARCH and is rejected with ERR_INVALID_STATE; the order stays
    RESEARCH.

    Design: Corner/state_machines/start_research_from_research_returns_invalid_state
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    rid = crew["researcher"]["id"]
    order = validate_success(
        api.create_survey_order(create_survey_order_payload(), make_coordinator_headers(cid)), 201)
    oid = order["id"]
    validate_success(
        api.create_research_packet(create_research_packet_payload(oid, rid, encumbrance_count=0),
                                   make_coordinator_headers(cid)), 201)
    validate_success(api.start_research(oid, make_coordinator_headers(cid)), 200)

    resp = api.start_research(oid, make_coordinator_headers(cid))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_survey_order(oid, make_coordinator_headers(cid)), 200)
    assert after["status"] == "RESEARCH"


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/cancel_delivered_order_terminal_lockdown
# ════════════════════════════════════════════════════════════════════════
def test_cancel_delivered_order_rejected(api):
    """PRD §3.1: "Both `DELIVERED` and `CANCELLED` are terminal."
    PRD §3.4: "Cancelling an order is a `Coordinator` action available from any
    state that is not `SEALED` or `DELIVERED` — concretely `INTAKE`, `RESEARCH`,
    `FIELD_READY`, `IN_FIELD`, `DATA_READY`, or `DRAFTING`."

    A fully DELIVERED order cannot be cancelled: cancel is not defined from DELIVERED,
    so it is rejected with ERR_INVALID_STATE and the order stays DELIVERED.

    Design: Corner/state_machines/cancel_delivered_order_terminal_lockdown
    """
    ctx = fx.issued_invoice(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    # Assemble + release a deliverable to reach DELIVERED.
    from test_helpers import create_deliverable_payload
    deliverable = validate_success(
        api.create_deliverable(create_deliverable_payload(ctx["order_id"], ctx["plat_id"], "PDF"),
                               make_coordinator_headers(cid)), 201)
    validate_success(api.release_deliverable(deliverable["id"], make_coordinator_headers(cid)), 200)
    delivered = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert delivered["status"] == "DELIVERED"

    resp = api.cancel_order(ctx["order_id"], make_coordinator_headers(cid))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert after["status"] == "DELIVERED"


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/seal_draft_plat_before_review_invalid_state
# ════════════════════════════════════════════════════════════════════════
def test_seal_drafted_plat_before_review_returns_invalid_state(api):
    """PRD §3.5: "Sealing is the most heavily guarded operation in the system,
    reserved to a `Surveyor`, and it moves a plat from `UNDER_REVIEW` to `SEALED`."
    PRD §2.9: "The state-machine legality of the requested transition
    (`ERR_INVALID_STATE`) is checked fifth, before any of the domain-specific
    business rules."

    Sealing a plat still in DRAFTED (never submitted to review) is not a defined
    transition and is rejected with ERR_INVALID_STATE; the plat stays DRAFTED.

    Design: Corner/state_machines/seal_draft_plat_before_review_invalid_state
    """
    ctx = fx.accepted_dataset(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    did = crew["drafter"]["id"]
    pls_id = crew["pls"]["id"]
    from test_helpers import create_plat_drawing_payload
    plat = validate_success(
        api.create_plat_drawing(create_plat_drawing_payload(ctx["order_id"], ctx["dataset_id"], did),
                                make_drafter_headers(did)), 201)
    ov = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)["version"]

    resp = api.seal_plat(plat["id"], seal_payload(pls_id, ov), make_surveyor_headers(pls_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_plat_drawing(plat["id"], make_coordinator_headers(cid)), 200)
    assert after["status"] == "DRAFTED"


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/research_packet_initial_state_is_open
# ════════════════════════════════════════════════════════════════════════
def test_new_research_packet_starts_open(api):
    """PRD §3.2: "A new packet's `status` is `OPEN`."

    A freshly created ResearchPacket has status OPEN.

    Design: Corner/state_machines/research_packet_initial_state_is_open
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    rid = crew["researcher"]["id"]
    order = validate_success(
        api.create_survey_order(create_survey_order_payload(), make_coordinator_headers(cid)), 201)
    packet = validate_success(
        api.create_research_packet(create_research_packet_payload(order["id"], rid, encumbrance_count=0),
                                   make_coordinator_headers(cid)), 201)
    assert packet["status"] == "OPEN"


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/research_packet_title_hold_reopen_cycle
# ════════════════════════════════════════════════════════════════════════
def test_packet_title_hold_then_reopen_to_in_progress(api):
    """PRD §3.2: "when `encumbrance_count` is at least one, the `Researcher` places
    the packet on hold, moving it to `TITLE_HOLD`; this advances nothing and leaves
    `research_clear` false."
    PRD §3.2: "from `TITLE_HOLD` the `Researcher` begins again, returning it to
    `IN_PROGRESS` (permitted whenever the parent order is still in `RESEARCH`) so
    the title issues can be re-investigated."

    A packet with encumbrance_count 1 goes IN_PROGRESS->TITLE_HOLD via hold, then
    TITLE_HOLD->IN_PROGRESS via begin, while the order stays RESEARCH.

    Design: Corner/state_machines/research_packet_title_hold_reopen_cycle
    """
    ctx = fx.order_at_in_progress_packet(encumbrance_count=1, survey_type="BOUNDARY", acreage=3)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    rid = crew["researcher"]["id"]
    pid = ctx["packet_id"]

    held = validate_success(api.hold_research_packet(pid, make_researcher_headers(rid)), 200)
    assert held["status"] == "TITLE_HOLD"

    reopened = validate_success(api.begin_research_packet(pid, make_researcher_headers(rid)), 200)
    assert reopened["status"] == "IN_PROGRESS"

    order = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert order["status"] == "RESEARCH"
