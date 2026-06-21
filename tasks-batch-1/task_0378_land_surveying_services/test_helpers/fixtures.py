"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require a survey order deep in its pipeline — past
research, fieldwork, data acceptance, drafting, and often sealing — which takes
10-20 API calls to reach. These helpers encapsulate those chains so each test
focuses on its single assertion.

All setup calls go through get_success_data() (lenient 2xx validator) so a broken
precondition surfaces as a clear setup failure, not a confusing assertion deep
inside a test.

Identity threading: every role is entity-backed by a CrewMember (PRD §2.1). After
creating a crew member, every role-gated call uses that crew member's real id via
make_*_headers(), never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_crew_member_payload,
    create_data_set_payload,
    create_deliverable_payload,
    create_field_assignment_payload,
    create_instrument_payload,
    create_instrument_reservation_payload,
    create_invoice_payload,
    create_plat_drawing_payload,
    create_pls_payload,
    create_research_packet_payload,
    create_revision_request_payload,
    create_survey_order_payload,
    issue_invoice_payload,
    payment_payload,
    seal_payload,
)
from .test_users import (
    make_billing_clerk_headers,
    make_coordinator_headers,
    make_drafter_headers,
    make_field_tech_headers,
    make_researcher_headers,
    make_surveyor_headers,
)


# ════════════════════════════════════════════════════════════════════════
# Crew bootstrap — one crew member per role, all entity-backed.
# ════════════════════════════════════════════════════════════════════════
def make_coordinator():
    """Create a COORDINATOR crew member (the bootstrap operator). Returns the entity."""
    coord = get_success_data(
        api_client.create_crew_member(
            create_crew_member_payload("COORDINATOR"),
            {"X-User-ID": "bootstrap", "X-User-Role": "Coordinator"},
        )
    )
    return coord


def make_crew(coord_id, role_type, **overrides):
    """Create a crew member of the given role_type, registered by the coordinator."""
    payload = (create_pls_payload(**overrides) if role_type == "PLS"
               else create_crew_member_payload(role_type, **overrides))
    return get_success_data(
        api_client.create_crew_member(payload, make_coordinator_headers(coord_id))
    )


def full_crew():
    """Create one crew member per role_type needed for a full pipeline run.

    Returns a dict with keys: coord, researcher, tech, drafter, pls, billing.
    Each value is the created CrewMember entity. The coordinator registers all
    of them (POST /crew-members is Coordinator-exclusive).
    """
    coord = make_coordinator()
    cid = coord["id"]
    return {
        "coord": coord,
        "researcher": make_crew(cid, "RESEARCHER"),
        "tech": make_crew(cid, "TECH"),
        "drafter": make_crew(cid, "DRAFTER"),
        "pls": make_crew(cid, "PLS"),
        "billing": make_crew(cid, "BILLING_CLERK"),
    }


# ════════════════════════════════════════════════════════════════════════
# Pipeline stage builders — each returns a context dict carrying ids + crew.
# ════════════════════════════════════════════════════════════════════════
def order_at_field_ready(crew=None, **order_overrides):
    """Create an order and drive it INTAKE -> RESEARCH -> FIELD_READY.

    Walks: create order, open research packet (encumbrance 0), start-research,
    begin packet, clear packet, clear-research. Returns ctx with order/packet/crew.
    """
    crew = crew or full_crew()
    cid = crew["coord"]["id"]
    rid = crew["researcher"]["id"]

    order = get_success_data(
        api_client.create_survey_order(
            create_survey_order_payload(**order_overrides), make_coordinator_headers(cid))
    )
    oid = order["id"]
    packet = get_success_data(
        api_client.create_research_packet(
            create_research_packet_payload(oid, rid, encumbrance_count=0),
            make_coordinator_headers(cid))
    )
    pid = packet["id"]
    get_success_data(api_client.start_research(oid, make_coordinator_headers(cid)))
    get_success_data(api_client.begin_research_packet(pid, make_researcher_headers(rid)))
    get_success_data(api_client.clear_research_packet(pid, make_researcher_headers(rid)))
    get_success_data(api_client.clear_research(oid, make_coordinator_headers(cid)))

    return {"crew": crew, "order": order, "order_id": oid, "packet": packet, "packet_id": pid}


def order_at_in_progress_packet(crew=None, encumbrance_count=0, **order_overrides):
    """Create an order in RESEARCH with an IN_PROGRESS research packet.

    Stops before clearing: create order, open packet, start-research, begin packet.
    Used by tests that assert on the packet at IN_PROGRESS (clear/hold boundaries).
    """
    crew = crew or full_crew()
    cid = crew["coord"]["id"]
    rid = crew["researcher"]["id"]

    order = get_success_data(
        api_client.create_survey_order(
            create_survey_order_payload(**order_overrides), make_coordinator_headers(cid))
    )
    oid = order["id"]
    packet = get_success_data(
        api_client.create_research_packet(
            create_research_packet_payload(oid, rid, encumbrance_count=encumbrance_count),
            make_coordinator_headers(cid))
    )
    pid = packet["id"]
    get_success_data(api_client.start_research(oid, make_coordinator_headers(cid)))
    get_success_data(api_client.begin_research_packet(pid, make_researcher_headers(rid)))

    return {"crew": crew, "order": order, "order_id": oid, "packet": packet, "packet_id": pid}


def accepted_dataset(crew=None, recorded_by="tech", closure_error_ppm=20, **order_overrides):
    """Drive an order all the way to an ACCEPTED dataset and DATA_READY.

    Builds on order_at_field_ready, then: create assignment, start it, complete it,
    record a dataset, reduce it, accept it (which advances order to DATA_READY).
    `recorded_by` selects which crew records the data ("tech" or "pls"); this is the
    segregation-of-duties source. Returns ctx adding assignment_id, dataset_id.
    """
    ctx = order_at_field_ready(crew=crew, **order_overrides)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]
    pls_id = crew["pls"]["id"]
    oid = ctx["order_id"]

    assignment = get_success_data(
        api_client.create_field_assignment(
            create_field_assignment_payload(
                oid, tid, "2026-07-01T09:00:00.000Z", "2026-07-01T13:00:00.000Z"),
            make_coordinator_headers(cid))
    )
    aid = assignment["id"]
    get_success_data(api_client.start_field_assignment(aid, make_field_tech_headers(tid)))
    get_success_data(api_client.complete_field_assignment(aid, make_field_tech_headers(tid)))

    recorder_id = tid if recorded_by == "tech" else pls_id
    recorder_headers = (make_field_tech_headers(recorder_id) if recorded_by == "tech"
                        else make_surveyor_headers(recorder_id))
    dataset = get_success_data(
        api_client.create_data_set(
            create_data_set_payload(oid, aid, recorder_id, closure_error_ppm=closure_error_ppm),
            recorder_headers)
    )
    dsid = dataset["id"]
    get_success_data(api_client.reduce_data_set(dsid, make_drafter_headers(crew["drafter"]["id"])))
    get_success_data(api_client.accept_data_set(dsid, make_surveyor_headers(pls_id)))

    ctx.update({"assignment": assignment, "assignment_id": aid,
                "dataset": dataset, "dataset_id": dsid, "recorded_by_id": recorder_id})
    return ctx


def plat_under_review(crew=None, recorded_by="tech", closure_error_ppm=20, **order_overrides):
    """Drive an order to an UNDER_REVIEW plat (order in DRAFTING).

    Builds on accepted_dataset, then: create plat (advances order to DRAFTING),
    submit-review. Returns ctx adding plat_id.
    """
    ctx = accepted_dataset(crew=crew, recorded_by=recorded_by,
                           closure_error_ppm=closure_error_ppm, **order_overrides)
    crew = ctx["crew"]
    did = crew["drafter"]["id"]
    plat = get_success_data(
        api_client.create_plat_drawing(
            create_plat_drawing_payload(ctx["order_id"], ctx["dataset_id"], did),
            make_drafter_headers(did))
    )
    pl_id = plat["id"]
    get_success_data(api_client.submit_plat_review(pl_id, make_drafter_headers(did)))
    ctx.update({"plat": plat, "plat_id": pl_id})
    return ctx


def order_version(ctx):
    """Read the order's current version (for OCC seal/issue payloads)."""
    order = get_success_data(
        api_client.get_survey_order(ctx["order_id"], make_coordinator_headers(ctx["crew"]["coord"]["id"]))
    )
    return order["version"]


def sealed_plat(crew=None, recorded_by="tech", closure_error_ppm=20, **order_overrides):
    """Drive an order to a SEALED plat (order in SEALED).

    Builds on plat_under_review, then reads the order version and seals the plat
    with the PLS (distinct from the recorder when recorded_by='tech'). Returns ctx
    with plat sealed and order SEALED.
    """
    ctx = plat_under_review(crew=crew, recorded_by=recorded_by,
                            closure_error_ppm=closure_error_ppm, **order_overrides)
    crew = ctx["crew"]
    pls_id = crew["pls"]["id"]
    ov = order_version(ctx)
    sealed = get_success_data(
        api_client.seal_plat(ctx["plat_id"], seal_payload(pls_id, ov),
                             make_surveyor_headers(pls_id))
    )
    ctx["plat"] = sealed
    return ctx


def issued_invoice(crew=None, **order_overrides):
    """Drive an order to a SEALED plat then create + issue an invoice.

    Returns ctx adding invoice_id with lifecycle_status ISSUED, order final_fee set.
    """
    ctx = sealed_plat(crew=crew, **order_overrides)
    crew = ctx["crew"]
    bid = crew["billing"]["id"]
    invoice = get_success_data(
        api_client.create_invoice(
            create_invoice_payload(ctx["order_id"], bid), make_billing_clerk_headers(bid))
    )
    inv_id = invoice["id"]
    ov = order_version(ctx)
    issued = get_success_data(
        api_client.issue_invoice(inv_id, issue_invoice_payload(ov), make_billing_clerk_headers(bid))
    )
    ctx.update({"invoice": issued, "invoice_id": inv_id})
    return ctx


def draft_invoice_on_sealed_order(crew=None, **order_overrides):
    """SEALED order with a DRAFT (not yet issued) invoice. Returns ctx adding invoice_id."""
    ctx = sealed_plat(crew=crew, **order_overrides)
    crew = ctx["crew"]
    bid = crew["billing"]["id"]
    invoice = get_success_data(
        api_client.create_invoice(
            create_invoice_payload(ctx["order_id"], bid), make_billing_clerk_headers(bid))
    )
    ctx.update({"invoice": invoice, "invoice_id": invoice["id"]})
    return ctx


def apply_client_change_revision(ctx):
    """On a SEALED-plat ctx, create + apply a CLIENT_CHANGE revision.

    Reverts plat to IN_REVISION and order to DRAFTING, adds reseal_fee to the
    order's estimate, and increments revision_count. Returns the applied revision.
    """
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    rev = get_success_data(
        api_client.create_revision_request(
            create_revision_request_payload(ctx["plat_id"], "CLIENT_CHANGE"),
            make_coordinator_headers(cid))
    )
    rev_id = rev["id"]
    applied = get_success_data(api_client.apply_revision(rev_id, make_coordinator_headers(cid)))
    ctx.setdefault("revisions", []).append(applied)
    return applied


def reseal_after_revision(ctx):
    """After a revision un-sealed the plat: resume-draft, submit-review, re-seal.

    Returns the order to SEALED. Returns the freshly sealed plat.
    """
    crew = ctx["crew"]
    did = crew["drafter"]["id"]
    pls_id = crew["pls"]["id"]
    pl_id = ctx["plat_id"]
    get_success_data(api_client.resume_draft(pl_id, make_drafter_headers(did)))
    get_success_data(api_client.submit_plat_review(pl_id, make_drafter_headers(did)))
    ov = order_version(ctx)
    sealed = get_success_data(
        api_client.seal_plat(pl_id, seal_payload(pls_id, ov), make_surveyor_headers(pls_id))
    )
    ctx["plat"] = sealed
    return sealed


# ════════════════════════════════════════════════════════════════════════
# Targeted helpers for cascade / reservation / scheduling scenarios.
# ════════════════════════════════════════════════════════════════════════
def field_ready_with_reservation(crew=None, instrument_overrides=None, **order_overrides):
    """FIELD_READY order with one SCHEDULED assignment holding one HELD reservation
    on a now-RESERVED instrument.

    Returns ctx with order_id, assignment_id, instrument_id, reservation_id, crew.
    """
    ctx = order_at_field_ready(crew=crew, **order_overrides)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]
    oid = ctx["order_id"]

    instrument = get_success_data(
        api_client.create_instrument(
            create_instrument_payload(**(instrument_overrides or {})),
            make_coordinator_headers(cid))
    )
    instr_id = instrument["id"]
    assignment = get_success_data(
        api_client.create_field_assignment(
            create_field_assignment_payload(
                oid, tid, "2026-07-01T09:00:00.000Z", "2026-07-01T13:00:00.000Z"),
            make_coordinator_headers(cid))
    )
    aid = assignment["id"]
    reservation = get_success_data(
        api_client.create_instrument_reservation(
            create_instrument_reservation_payload(aid, instr_id), make_coordinator_headers(cid))
    )
    ctx.update({
        "instrument": instrument, "instrument_id": instr_id,
        "assignment": assignment, "assignment_id": aid,
        "reservation": reservation, "reservation_id": reservation["id"],
    })
    return ctx


def crew_with_scheduled_assignments(crew=None, windows=None, **order_overrides):
    """A TECH crew member with N non-overlapping SCHEDULED assignments on a
    FIELD_READY order, raising its open_assignment_count to len(windows).

    `windows` is a list of (start, end) ISO 8601 strings. Returns ctx with
    tech_id and the list of created assignment ids.
    """
    windows = windows or [
        ("2026-07-01T08:00:00.000Z", "2026-07-01T10:00:00.000Z"),
        ("2026-07-01T11:00:00.000Z", "2026-07-01T13:00:00.000Z"),
        ("2026-07-01T14:00:00.000Z", "2026-07-01T16:00:00.000Z"),
    ]
    ctx = order_at_field_ready(crew=crew, **order_overrides)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]
    oid = ctx["order_id"]
    assignment_ids = []
    for start, end in windows:
        fa = get_success_data(
            api_client.create_field_assignment(
                create_field_assignment_payload(oid, tid, start, end),
                make_coordinator_headers(cid))
        )
        assignment_ids.append(fa["id"])
    ctx.update({"tech_id": tid, "assignment_ids": assignment_ids})
    return ctx
