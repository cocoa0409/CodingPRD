"""Composite setup helpers for multi-step test prerequisites.

The closeout pipeline is phase-gated, so most interesting claims need the system
driven through mobilization, punch operations, substantial completion, occupancy,
closeout package assembly, and final release before the asserted behavior is even
reachable. These helpers encapsulate those drives.

Setup calls use get_success_data() so failures surface as clear "Setup step failed"
errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    clock_payload,
    create_closeout_document_payload,
    create_project_payload,
    create_punch_item_payload,
    create_punch_walk_payload,
    create_retainage_release_payload,
    create_trade_package_payload,
    create_training_session_payload,
    create_warranty_case_payload,
    lien_waiver_decision_payload,
    lien_waiver_submission_payload,
)
from .test_users import TEST_USERS, make_subcontractor_headers

PM = TEST_USERS["gc_pm_headers"]
INSP = TEST_USERS["gc_inspector_headers"]
OWNER = TEST_USERS["owner_rep_headers"]

# Default walk window; the logical clock starts at 2026-08-01T00:00:00Z (PRD §2.4),
# so this window is always in the future at creation time.
DEFAULT_WALK_START = "2026-08-03T09:00:00Z"
DEFAULT_WALK_END = "2026-08-03T10:00:00Z"
DEFAULT_WALK_COMPLETE_AT = "2026-08-03T10:00:00Z"
DEFAULT_SC_CLOCK = "2026-08-03T10:00:00Z"
DEFAULT_OCCUPANCY_DATE = "2026-08-04T00:00:00Z"
DEFAULT_TRAINING_START = "2026-08-05T09:00:00Z"
DEFAULT_TRAINING_END = "2026-08-05T10:00:00Z"


def _ok(resp):
    return get_success_data(resp)


# ─── Tier 0: single-call primitives ─────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the logical clock (GCProjectManager-only test-driving capability)."""
    return _ok(api_client.set_logical_clock(clock_payload(to_iso8601), PM))


def get_project(project_id: str) -> dict:
    return _ok(api_client.get_project(project_id, PM))


def get_trade(trade_id: str) -> dict:
    return _ok(api_client.get_trade_package(trade_id, PM))


def get_item(item_id: str) -> dict:
    return _ok(api_client.get_punch_item(item_id, PM))


def get_session(session_id: str) -> dict:
    return _ok(api_client.get_training_session(session_id, PM))


def new_project(name="Test Project", contract_value_cents=10_000_000, retainage_pct=0.10,
                reduction_policy="STANDARD", warranty_sla_mode="CALENDAR") -> dict:
    return _ok(api_client.create_project(
        create_project_payload(
            name=name,
            contract_value_cents=contract_value_cents,
            retainage_pct=retainage_pct,
            reduction_policy=reduction_policy,
            warranty_sla_mode=warranty_sla_mode,
        ),
        PM,
    ))


def new_trade(project_id: str, trade_name="ELECTRICAL", responsible_type="SUBCONTRACTOR",
              subcontractor_org="SparkyCo") -> dict:
    return _ok(api_client.create_trade_package(
        create_trade_package_payload(
            project_id,
            trade_name=trade_name,
            responsible_type=responsible_type,
            subcontractor_org=subcontractor_org,
        ),
        PM,
    ))


def begin_punch(project_id: str) -> dict:
    return _ok(api_client.begin_punch(project_id, PM))


def schedule_walk(project_id: str, trade_id: str, lead_inspector_id="insp-lead-1",
                  scheduled_start=DEFAULT_WALK_START, scheduled_end=DEFAULT_WALK_END) -> dict:
    return _ok(api_client.create_punch_walk(
        create_punch_walk_payload(
            project_id,
            trade_id,
            lead_inspector_id=lead_inspector_id,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
        ),
        PM,
    ))


def complete_walk(walk_id: str) -> dict:
    return _ok(api_client.complete_punch_walk(walk_id, INSP))


def create_item(project_id: str, trade_id: str, title="Paint touch-up", severity="MINOR",
                location_area="R1", photo_ref="img-1", punch_walk_id=None) -> dict:
    return _ok(api_client.create_punch_item(
        create_punch_item_payload(
            project_id,
            trade_id,
            title=title,
            severity=severity,
            location_area=location_area,
            photo_ref=photo_ref,
            punch_walk_id=punch_walk_id,
        ),
        INSP,
    ))


def create_items(project_id: str, trade_id: str, severities, title_prefix="Item") -> list:
    """Create one punch item per severity in the given iterable. Returns item dicts."""
    items = []
    for idx, severity in enumerate(severities, start=1):
        items.append(create_item(
            project_id, trade_id,
            title=f"{title_prefix}-{idx}", severity=severity,
            location_area=f"R{idx}", photo_ref=f"{title_prefix.lower()}-{idx}",
        ))
    return items


def mark_ready(item_id: str, trade_id: str) -> dict:
    """Mark-ready as the owning SubcontractorRep (X-User-ID == TradePackage.id)."""
    return _ok(api_client.mark_punch_item_ready(item_id, make_subcontractor_headers(trade_id)))


def submit_doc(project_id: str, trade_id: str, doc_type: str, file_ref: str) -> dict:
    """Submit a closeout document as the owning SubcontractorRep."""
    return _ok(api_client.create_closeout_document(
        create_closeout_document_payload(project_id, trade_id, doc_type=doc_type, file_ref=file_ref),
        make_subcontractor_headers(trade_id),
    ))


def approve_doc(doc_id: str) -> dict:
    return _ok(api_client.approve_closeout_document(doc_id, PM))


def submit_waiver(trade_id: str, waiver_type="UNCONDITIONAL", amount_cents=1_000_000,
                  file_ref="wvr-1") -> dict:
    """Submit the trade's lien waiver as the owning SubcontractorRep."""
    return _ok(api_client.submit_lien_waiver(
        trade_id,
        lien_waiver_submission_payload(
            waiver_type=waiver_type, amount_cents=amount_cents, file_ref=file_ref
        ),
        make_subcontractor_headers(trade_id),
    ))


def decide_waiver(trade_id: str, decision="ACCEPT", rejection_reason=None) -> dict:
    overrides = {}
    if rejection_reason is not None:
        overrides["rejection_reason"] = rejection_reason
    return _ok(api_client.decide_lien_waiver(
        trade_id, lien_waiver_decision_payload(decision, **overrides), PM
    ))


def schedule_training(project_id: str, trade_id: str, system_name="AHU-1 controls",
                      location_room="TR-1", scheduled_start=DEFAULT_TRAINING_START,
                      scheduled_end=DEFAULT_TRAINING_END) -> dict:
    return _ok(api_client.create_training_session(
        create_training_session_payload(
            project_id,
            trade_id,
            system_name=system_name,
            location_room=location_room,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
        ),
        PM,
    ))


def conduct_training(session_id: str, attendee_count=3) -> dict:
    return _ok(api_client.conduct_training_session(session_id, {"attendee_count": attendee_count}, PM))


def create_release(project_id: str, kind: str) -> dict:
    """Create a release carrying the project's current version (OCC, PRD §2.7)."""
    version = get_project(project_id)["version"]
    return _ok(api_client.create_retainage_release(
        create_retainage_release_payload(project_id, kind, version), PM
    ))


def approve_release(release_id: str) -> dict:
    return _ok(api_client.approve_retainage_release(release_id, OWNER))


def report_warranty_case(project_id: str, title="Callback issue", severity="MINOR",
                         description="Issue reported after close") -> dict:
    return _ok(api_client.create_warranty_case(
        create_warranty_case_payload(project_id, title=title, severity=severity, description=description),
        OWNER,
    ))


# ─── Tier 1/2: state progression + hierarchy ────────────────────────────────

def setup_walked_project(*, name="Test Project", reduction_policy="STANDARD",
                         warranty_sla_mode="CALENDAR", contract_value_cents=10_000_000,
                         retainage_pct=0.10, trade_name="ELECTRICAL",
                         responsible_type="SUBCONTRACTOR", item_severities=(),
                         walk_start=DEFAULT_WALK_START, walk_end=DEFAULT_WALK_END,
                         walk_complete_at=DEFAULT_WALK_COMPLETE_AT,
                         lead_inspector_id="insp-lead-1") -> dict:
    """Project + one trade + begin-punch + one COMPLETED walk for the trade,
    plus one punch item per severity in ``item_severities`` (created while
    PUNCH_ACTIVE). Returns {"project", "trade", "walk", "items"}."""
    project = new_project(name, contract_value_cents, retainage_pct,
                          reduction_policy, warranty_sla_mode)
    trade = new_trade(project["id"], trade_name, responsible_type)
    project = begin_punch(project["id"])
    walk = schedule_walk(project["id"], trade["id"], lead_inspector_id, walk_start, walk_end)
    set_clock(walk_complete_at)
    walk = complete_walk(walk["id"])
    items = create_items(project["id"], trade["id"], item_severities)
    return {"project": get_project(project["id"]), "trade": trade, "walk": walk, "items": items}


# ─── Tier 3: lifecycle drivers ──────────────────────────────────────────────

def drive_to_sc_review(ctx: dict) -> dict:
    ctx["project"] = _ok(api_client.request_sc_review(ctx["project"]["id"], PM))
    return ctx


def drive_to_substantially_complete(ctx: dict, sc_clock=DEFAULT_SC_CLOCK) -> dict:
    """Request the SC review, pin the clock, then record the owner's approval.
    The SC/warranty-start stamps equal ``sc_clock`` (PRD §3.4)."""
    drive_to_sc_review(ctx)
    set_clock(sc_clock)
    ctx["project"] = _ok(api_client.determine_substantial_completion(
        ctx["project"]["id"], {"approved": True}, OWNER
    ))
    return ctx


def drive_to_closeout(ctx: dict, occupancy_date=DEFAULT_OCCUPANCY_DATE) -> dict:
    """Register beneficial occupancy, then start closeout."""
    _ok(api_client.register_beneficial_occupancy(
        ctx["project"]["id"], {"occupancy_date": occupancy_date}, OWNER
    ))
    ctx["project"] = _ok(api_client.start_closeout(ctx["project"]["id"], PM))
    return ctx


def submit_and_approve_all_docs(project_id: str, trade_id: str) -> list:
    """Submit + approve the three closeout documents (O&M, warranty, as-built)."""
    approved = []
    for doc_type in ("OM_MANUAL", "WARRANTY_DOC", "AS_BUILT"):
        doc = submit_doc(project_id, trade_id, doc_type, f"{doc_type.lower()}-ref")
        approved.append(approve_doc(doc["id"]))
    return approved


def schedule_and_conduct_training(project_id: str, trade_id: str, room="TR-1",
                                  start=DEFAULT_TRAINING_START, end=DEFAULT_TRAINING_END,
                                  attendee_count=3) -> dict:
    session = schedule_training(project_id, trade_id, location_room=room,
                                scheduled_start=start, scheduled_end=end)
    set_clock(start)
    return conduct_training(session["id"], attendee_count)


def complete_trade_closeout_package(ctx: dict,
                                    training_start=DEFAULT_TRAINING_START,
                                    training_end=DEFAULT_TRAINING_END,
                                    training_room="TR-1") -> dict:
    """Complete the trade's closeout package while CLOSEOUT_IN_PROGRESS: the three
    documents approved, the UNCONDITIONAL waiver accepted, one training session
    conducted. The last flip auto-advances the project (PRD §2.8)."""
    project_id, trade_id = ctx["project"]["id"], ctx["trade"]["id"]
    submit_and_approve_all_docs(project_id, trade_id)
    submit_waiver(trade_id)
    decide_waiver(trade_id, "ACCEPT")
    schedule_and_conduct_training(project_id, trade_id, room=training_room,
                                  start=training_start, end=training_end)
    ctx["project"] = get_project(project_id)
    ctx["trade"] = get_trade(trade_id)
    return ctx


def drive_to_final_release_pending(ctx: dict, occupancy_date=DEFAULT_OCCUPANCY_DATE,
                                   training_start=DEFAULT_TRAINING_START,
                                   training_end=DEFAULT_TRAINING_END,
                                   training_room="TR-1") -> dict:
    """From SUBSTANTIALLY_COMPLETE: register occupancy, start closeout, complete the
    trade package so the project auto-advances. Requires zero open items."""
    drive_to_closeout(ctx, occupancy_date)
    return complete_trade_closeout_package(
        ctx, training_start=training_start, training_end=training_end,
        training_room=training_room,
    )


# ─── Tier 5: terminal state ─────────────────────────────────────────────────

def drive_to_closed(ctx: dict, occupancy_date=DEFAULT_OCCUPANCY_DATE,
                    training_start=DEFAULT_TRAINING_START,
                    training_end=DEFAULT_TRAINING_END,
                    training_room="TR-1") -> dict:
    """Entire lifecycle through CLOSED: FINAL release created + PAID, then close."""
    drive_to_final_release_pending(
        ctx, occupancy_date=occupancy_date, training_start=training_start,
        training_end=training_end, training_room=training_room,
    )
    final_release = create_release(ctx["project"]["id"], "FINAL")
    approve_release(final_release["id"])
    ctx["final_release"] = final_release
    ctx["project"] = _ok(api_client.close_project(ctx["project"]["id"], PM))
    return ctx


# ─── Convenience composites used by several tests ───────────────────────────

def setup_substantially_complete_project(*, item_severities=(), **kwargs) -> dict:
    """Walked single-trade project driven to SUBSTANTIALLY_COMPLETE.

    ``kwargs`` forwards to setup_walked_project (policy/mode/contract knobs) and
    may include ``sc_clock`` to pin the SC instant.
    """
    sc_clock = kwargs.pop("sc_clock", DEFAULT_SC_CLOCK)
    ctx = setup_walked_project(item_severities=item_severities, **kwargs)
    return drive_to_substantially_complete(ctx, sc_clock=sc_clock)


def setup_closeout_project(*, item_severities=(), **kwargs) -> dict:
    """Walked single-trade project driven to CLOSEOUT_IN_PROGRESS."""
    ctx = setup_substantially_complete_project(item_severities=item_severities, **kwargs)
    return drive_to_closeout(ctx)


def setup_final_release_pending_project(**kwargs) -> dict:
    """Full closeout package completed; project auto-advanced."""
    ctx = setup_closeout_project(**kwargs)
    return complete_trade_closeout_package(ctx)


def setup_closed_project(**kwargs) -> dict:
    """Entire lifecycle through CLOSED (for warranty-window tests)."""
    occupancy_date = kwargs.pop("occupancy_date", DEFAULT_OCCUPANCY_DATE)
    training_start = kwargs.pop("training_start", DEFAULT_TRAINING_START)
    training_end = kwargs.pop("training_end", DEFAULT_TRAINING_END)
    ctx = setup_substantially_complete_project(**kwargs)
    return drive_to_closed(ctx, occupancy_date=occupancy_date,
                           training_start=training_start, training_end=training_end)


def setup_ready_item(**kwargs) -> dict:
    """Walked project with one item already marked READY_FOR_REVIEW by its trade."""
    ctx = setup_walked_project(item_severities=(kwargs.pop("item_severity", "MINOR"),), **kwargs)
    item = ctx["items"][0]
    ctx["items"][0] = mark_ready(item["id"], ctx["trade"]["id"])
    return ctx
