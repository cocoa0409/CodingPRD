"""Composite state builders.

Every builder drives the public API only and returns the freshly-read entities
it produced, so a test can start from a realistic mid-lifecycle state without
re-inventing the call chain.  Builders never assert business outcomes; they use
`get_success_data` so that a broken setup surfaces as a loud failure.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    acknowledgement_payload,
    create_class_entry_payload,
    create_class_payload,
    create_compliance_case_payload,
    create_coverage_shift_payload,
    create_division_payload,
    create_entry_payload,
    create_footing_maintenance_payload,
    create_horse_payload,
    create_official_assignment_payload,
    create_official_payload,
    create_results_payload,
    create_ring_payload,
    create_ring_slot_payload,
    create_rider_payload,
    create_show_payload,
    placing_row,
)
from .test_users import (
    TEST_USERS,
    make_exhibitor_headers,
    make_judge_headers,
    make_steward_headers,
)

SECRETARY = TEST_USERS["show_secretary_headers"]
OFFICER = TEST_USERS["federation_officer_headers"]
RING_MASTER = TEST_USERS["ring_master_headers"]
GROUNDS = TEST_USERS["grounds_manager_headers"]


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Move the server's logical current UTC instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OFFICER))


def create_show(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_show(create_show_payload(**overrides), SECRETARY))


def get_show(show_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_show(show_id, SECRETARY))


def create_ring(show_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_ring(show_id, create_ring_payload(**overrides), SECRETARY))


def get_ring(ring_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_ring(ring_id, GROUNDS))


def ring_version(ring_id: str) -> int:
    return get_ring(ring_id)["version"]


def create_division(show_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_division(show_id, create_division_payload(**overrides), SECRETARY)
    )


def create_class(division_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_class(division_id, create_class_payload(**overrides), SECRETARY)
    )


def get_class(class_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_class(class_id, SECRETARY))


def class_version(class_id: str) -> int:
    return get_class(class_id)["version"]


def create_rider(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_rider(create_rider_payload(**overrides), OFFICER))


def create_horse(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_horse(create_horse_payload(**overrides), OFFICER))


def create_official(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_official(create_official_payload(**overrides), OFFICER))


def get_official(official_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_official(official_id, SECRETARY))


def official_load(official_id: str) -> int:
    return get_official(official_id)["assigned_minutes"]


def get_entry(entry_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_entry(entry_id, SECRETARY))


def get_class_entry(class_entry_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_class_entry(class_entry_id, SECRETARY))


def get_slot(slot_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_ring_slot(slot_id, RING_MASTER))


# --------------------------------------------------------------------------- #
# Tier 1 — licence state progression
# --------------------------------------------------------------------------- #
def submit_license(show_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.submit_show_license(show_id, SECRETARY))


def decide_license(show_id: str, decision: str, correction_note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if correction_note is not None:
        payload["correction_note"] = correction_note
    return get_success_data(api_client.decide_show_license(show_id, payload, OFFICER))


def approve_license(show_id: str) -> Dict[str, Any]:
    """DRAFT -> SUBMITTED -> APPROVED in one step."""
    submit_license(show_id)
    return decide_license(show_id, "APPROVE")


def open_class(class_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.open_class(class_id, SECRETARY))


def build_show_with_class_list(
    show_overrides: Optional[Dict[str, Any]] = None,
    division_overrides: Optional[Dict[str, Any]] = None,
    class_specs: Optional[Sequence[Dict[str, Any]]] = None,
    ring_specs: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Show + optional rings + one division + its classes, licence still DRAFT.

    `class_specs` / `ring_specs` are lists of factory overrides, one per row.
    """
    show = create_show(**(show_overrides or {}))
    rings = [create_ring(show["id"], **spec) for spec in (ring_specs or [])]
    division = create_division(show["id"], **(division_overrides or {}))
    specs = class_specs if class_specs is not None else [{}]
    classes = [create_class(division["id"], **spec) for spec in specs]
    return {
        "show": show,
        "show_id": show["id"],
        "rings": rings,
        "ring": rings[0] if rings else None,
        "ring_id": rings[0]["id"] if rings else None,
        "division": division,
        "division_id": division["id"],
        "classes": classes,
        "class_ids": [c["id"] for c in classes],
        "class_id": classes[0]["id"] if classes else None,
    }


def build_approved_show(
    show_overrides: Optional[Dict[str, Any]] = None,
    division_overrides: Optional[Dict[str, Any]] = None,
    class_specs: Optional[Sequence[Dict[str, Any]]] = None,
    ring_specs: Optional[Sequence[Dict[str, Any]]] = None,
    open_classes: bool = True,
) -> Dict[str, Any]:
    """Licence APPROVED; when `open_classes`, every class is moved to OPEN."""
    ctx = build_show_with_class_list(
        show_overrides=show_overrides,
        division_overrides=division_overrides,
        class_specs=class_specs,
        ring_specs=ring_specs,
    )
    ctx["show"] = approve_license(ctx["show_id"])
    if open_classes:
        ctx["classes"] = [open_class(class_id) for class_id in ctx["class_ids"]]
    else:
        ctx["classes"] = [get_class(class_id) for class_id in ctx["class_ids"]]
    ctx["division"] = _find_division(ctx["show_id"], ctx["division_id"])
    return ctx


def _find_division(show_id: str, division_id: str) -> Dict[str, Any]:
    rows, _meta = _paginated(api_client.list_show_divisions(show_id, SECRETARY))
    for row in rows:
        if row["id"] == division_id:
            return row
    return {}


def _paginated(response):
    body = response.json()
    return body["data"], body["meta"]


# --------------------------------------------------------------------------- #
# Tier 2 — registry hierarchy
# --------------------------------------------------------------------------- #
def build_registry(
    rider_count: int = 1,
    horse_count: int = 1,
    official_specs: Optional[Sequence[Dict[str, Any]]] = None,
    rider_overrides: Optional[Sequence[Dict[str, Any]]] = None,
    horse_overrides: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    riders = [
        create_rider(**((rider_overrides or [])[i] if rider_overrides and i < len(rider_overrides) else {}))
        for i in range(rider_count)
    ]
    horses = [
        create_horse(**((horse_overrides or [])[i] if horse_overrides and i < len(horse_overrides) else {}))
        for i in range(horse_count)
    ]
    officials = [create_official(**spec) for spec in (official_specs or [])]
    return {
        "riders": riders,
        "rider": riders[0] if riders else None,
        "rider_id": riders[0]["id"] if riders else None,
        "horses": horses,
        "horse": horses[0] if horses else None,
        "horse_id": horses[0]["id"] if horses else None,
        "officials": officials,
    }


def build_judge_and_steward(discipline: str = "JUMPER", level: int = 2) -> Dict[str, Any]:
    """One JUDGE-licensed and one STEWARD-licensed official for the discipline."""
    judge = create_official(
        license_roles=["JUDGE"], license_level=level, licensed_disciplines=[discipline]
    )
    steward = create_official(
        license_roles=["STEWARD"], license_level=level, licensed_disciplines=[discipline]
    )
    return {
        "judge": judge,
        "judge_id": judge["id"],
        "judge_headers": make_judge_headers(judge["id"]),
        "steward": steward,
        "steward_id": steward["id"],
        "steward_headers": make_steward_headers(steward["id"]),
    }


# --------------------------------------------------------------------------- #
# Tier 3 — entry lifecycle shortcuts
# --------------------------------------------------------------------------- #
def build_entry(
    show_id: str,
    rider_id: str,
    horse_id: str,
    class_ids: Iterable[str] = (),
    requested_stall_count: int = 0,
) -> Dict[str, Any]:
    """RECEIVED / UNBILLED entry plus one ENTERED class entry per class id."""
    headers = make_exhibitor_headers(rider_id)
    entry = get_success_data(
        api_client.create_entry(
            show_id,
            create_entry_payload(rider_id, horse_id, requested_stall_count=requested_stall_count),
            headers,
        )
    )
    class_entries = [
        get_success_data(
            api_client.create_class_entry(create_class_entry_payload(entry["id"], class_id), headers)
        )
        for class_id in class_ids
    ]
    return {
        "entry": get_entry(entry["id"]),
        "entry_id": entry["id"],
        "rider_id": rider_id,
        "horse_id": horse_id,
        "exhibitor_headers": headers,
        "class_entries": class_entries,
        "class_entry_ids": [ce["id"] for ce in class_entries],
        "class_entry": class_entries[0] if class_entries else None,
        "class_entry_id": class_entries[0]["id"] if class_entries else None,
    }


def invoice_entry(entry_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.invoice_entry(entry_id, SECRETARY))


def pay_entry(entry_id: str, rider_id: str, amount_cents: Optional[int] = None) -> Dict[str, Any]:
    """Pay the invoiced amount (defaults to the entry's own `total_due_cents`)."""
    if amount_cents is None:
        amount_cents = get_entry(entry_id)["total_due_cents"]
    return get_success_data(
        api_client.pay_entry(
            entry_id, {"amount_cents": amount_cents}, make_exhibitor_headers(rider_id)
        )
    )


def settle_entry(entry_id: str, rider_id: str) -> Dict[str, Any]:
    """UNBILLED -> INVOICED -> PAID for the full invoiced amount."""
    invoice_entry(entry_id)
    return pay_entry(entry_id, rider_id)


def verify_entry(entry_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.verify_entry(entry_id, SECRETARY))


def accept_entry(entry_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.accept_entry(entry_id, SECRETARY))


def confirm_entry(entry_id: str) -> Dict[str, Any]:
    """RECEIVED -> VERIFIED -> ACCEPTED (the join that confirms class entries)."""
    verify_entry(entry_id)
    return accept_entry(entry_id)


def build_confirmed_entry(
    show_id: str,
    rider_id: str,
    horse_id: str,
    class_ids: Iterable[str] = (),
    requested_stall_count: int = 0,
    paid: bool = True,
) -> Dict[str, Any]:
    """Entry taken all the way to ACCEPTED (and PAID unless `paid=False`)."""
    ctx = build_entry(show_id, rider_id, horse_id, class_ids, requested_stall_count)
    if paid:
        settle_entry(ctx["entry_id"], rider_id)
    ctx["entry"] = confirm_entry(ctx["entry_id"])
    ctx["class_entries"] = [get_class_entry(ce_id) for ce_id in ctx["class_entry_ids"]]
    return ctx


def build_field(
    show_id: str,
    class_ids: Sequence[str],
    count: int,
    requested_stall_count: int = 0,
    paid: bool = True,
    confirm: bool = True,
) -> List[Dict[str, Any]]:
    """`count` distinct rider/horse pairs entered into every class in `class_ids`."""
    field: List[Dict[str, Any]] = []
    for _ in range(count):
        rider = create_rider()
        horse = create_horse()
        if confirm:
            ctx = build_confirmed_entry(
                show_id, rider["id"], horse["id"], class_ids, requested_stall_count, paid=paid
            )
        else:
            ctx = build_entry(show_id, rider["id"], horse["id"], class_ids, requested_stall_count)
            if paid:
                settle_entry(ctx["entry_id"], rider["id"])
        ctx["rider"] = rider
        ctx["horse"] = horse
        field.append(ctx)
    return field


def withdraw_entry(entry_id: str, rider_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.withdraw_entry(entry_id, make_exhibitor_headers(rider_id))
    )


# --------------------------------------------------------------------------- #
# Tier 4 — scheduling, coverage and run-day progression
# --------------------------------------------------------------------------- #
def book_slot(ring_id: str, class_id: str, start_utc: str,
              expected_ring_version: Optional[int] = None) -> Dict[str, Any]:
    """Read the ring's current version, then book the competition slot."""
    if expected_ring_version is None:
        expected_ring_version = ring_version(ring_id)
    return get_success_data(
        api_client.create_ring_slot(
            create_ring_slot_payload(ring_id, class_id, start_utc, expected_ring_version),
            RING_MASTER,
        )
    )


def card_official(official_id: str, slot_id: str, official_role: str = "JUDGE") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_official_assignment(
            create_official_assignment_payload(official_id, slot_id, official_role), SECRETARY
        )
    )


def card_judge_and_steward(slot_id: str, judge_id: str, steward_id: str) -> Dict[str, Any]:
    return {
        "judge_assignment": card_official(judge_id, slot_id, "JUDGE"),
        "steward_assignment": card_official(steward_id, slot_id, "STEWARD"),
    }


def create_coverage_shift(show_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_coverage_shift(show_id, create_coverage_shift_payload(**overrides), GROUNDS)
    )


def activate_coverage_shift(shift_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.activate_coverage_shift(shift_id, GROUNDS))


def build_active_coverage(
    show_id: str,
    checkin_clock: str = TEST_DEFAULTS["COMPETITION_DAY_CLOCK"],
    shift_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A VETERINARIAN shift moved to ACTIVE (the clock is advanced to check in)."""
    shift = create_coverage_shift(show_id, **(shift_overrides or {}))
    set_clock(checkin_clock)
    return activate_coverage_shift(shift["id"])


def start_slot(slot_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_ring_slot(slot_id, RING_MASTER))


def record_footing_maintenance(ring_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_footing_maintenance(
            ring_id, create_footing_maintenance_payload(**overrides), GROUNDS
        )
    )


def build_scheduled_class(
    entry_count: int = 3,
    slot_start_utc: str = TEST_DEFAULTS["SLOT_START_UTC"],
    show_overrides: Optional[Dict[str, Any]] = None,
    division_overrides: Optional[Dict[str, Any]] = None,
    class_specs: Optional[Sequence[Dict[str, Any]]] = None,
    ring_specs: Optional[Sequence[Dict[str, Any]]] = None,
    requested_stall_count: int = 0,
    paid: bool = True,
) -> Dict[str, Any]:
    """APPROVED show, OPEN class with a confirmed field, and a booked ring slot."""
    ctx = build_approved_show(
        show_overrides=show_overrides,
        division_overrides=division_overrides,
        class_specs=class_specs,
        ring_specs=ring_specs or [{}],
    )
    ctx["field"] = build_field(
        ctx["show_id"], [ctx["class_id"]], entry_count,
        requested_stall_count=requested_stall_count, paid=paid,
    )
    ctx["slot"] = book_slot(ctx["ring_id"], ctx["class_id"], slot_start_utc)
    ctx["slot_id"] = ctx["slot"]["id"]
    ctx["classes"][0] = get_class(ctx["class_id"])
    return ctx


def build_running_class(
    entry_count: int = 3,
    slot_start_utc: str = TEST_DEFAULTS["SLOT_START_UTC"],
    checkin_clock: str = TEST_DEFAULTS["COMPETITION_DAY_CLOCK"],
    **kwargs,
) -> Dict[str, Any]:
    """Everything `build_scheduled_class` produces, then officials + coverage + start."""
    ctx = build_scheduled_class(entry_count=entry_count, slot_start_utc=slot_start_utc, **kwargs)
    ctx.update(build_judge_and_steward())
    ctx["assignments"] = card_judge_and_steward(ctx["slot_id"], ctx["judge_id"], ctx["steward_id"])
    ctx["coverage_shift"] = build_active_coverage(ctx["show_id"], checkin_clock=checkin_clock)
    ctx["slot"] = start_slot(ctx["slot_id"])
    ctx["classes"][0] = get_class(ctx["class_id"])
    return ctx


# --------------------------------------------------------------------------- #
# Tier 5 — results, standings submission and compliance finalisation
# --------------------------------------------------------------------------- #
def record_results(class_id: str, judge_official_id: str, placings: Sequence[Dict[str, Any]],
                   actual_minutes: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_class_results(
            class_id,
            create_results_payload(list(placings), actual_minutes),
            make_judge_headers(judge_official_id),
        )
    )


def default_placings(class_entry_ids: Sequence[str], base_seconds: float = 61.5) -> List[Dict[str, Any]]:
    """Place the given class entries 1..n in order, one second apart."""
    return [
        placing_row(ce_id, index + 1, base_seconds + index)
        for index, ce_id in enumerate(class_entry_ids)
    ]


def post_results(class_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.post_class_results(class_id, SECRETARY))


def void_results(class_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.void_class_results(class_id, SECRETARY))


def build_judged_class(
    entry_count: int = 3,
    actual_minutes: int = 26,
    **kwargs,
) -> Dict[str, Any]:
    """A class run to JUDGED with every confirmed class entry placed 1..n."""
    ctx = build_running_class(entry_count=entry_count, **kwargs)
    ce_ids = [ctx_entry["class_entry_id"] for ctx_entry in ctx["field"]]
    ctx["placings"] = default_placings(ce_ids)
    ctx["classes"][0] = record_results(
        ctx["class_id"], ctx["judge_id"], ctx["placings"], actual_minutes
    )
    ctx["class_entry_ids"] = ce_ids
    return ctx


def build_posted_class(entry_count: int = 3, actual_minutes: int = 26, **kwargs) -> Dict[str, Any]:
    """A class whose prize money has been posted (RESULTS_POSTED)."""
    ctx = build_judged_class(entry_count=entry_count, actual_minutes=actual_minutes, **kwargs)
    ctx["classes"][0] = post_results(ctx["class_id"])
    ctx["show"] = get_show(ctx["show_id"])
    return ctx


def submit_points(class_id: str, expected_version: Optional[int] = None) -> Dict[str, Any]:
    if expected_version is None:
        expected_version = class_version(class_id)
    return get_success_data(
        api_client.create_point_submission(
            class_id, {"expected_class_version": expected_version}, SECRETARY
        )
    )


def acknowledge(submission_id: str, standings_body: str, outcome: str,
                body_reference: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.acknowledge_point_submission(
            submission_id, acknowledgement_payload(standings_body, outcome, body_reference), OFFICER
        )
    )


def build_point_submission(entry_count: int = 3, actual_minutes: int = 26, **kwargs) -> Dict[str, Any]:
    """A posted class whose points have been submitted to the standings bodies."""
    ctx = build_posted_class(entry_count=entry_count, actual_minutes=actual_minutes, **kwargs)
    ctx["submission"] = submit_points(ctx["class_id"])
    ctx["submission_id"] = ctx["submission"]["id"]
    return ctx


def open_compliance_case(entry_id: str, steward_official_id: str, case_type: str = "DRUG_TEST",
                         **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_compliance_case(
            entry_id,
            create_compliance_case_payload(steward_official_id, case_type, **overrides),
            make_steward_headers(steward_official_id),
        )
    )


def record_finding(case_id: str, finding: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_case_finding(case_id, {"finding": finding}, OFFICER)
    )


def build_multi_class_show(
    class_specs: Sequence[Dict[str, Any]],
    entry_plan: Sequence[Dict[str, Any]],
    show_overrides: Optional[Dict[str, Any]] = None,
    division_overrides: Optional[Dict[str, Any]] = None,
    ring_specs: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """An APPROVED show with several OPEN classes and a hand-drawn entry sheet.

    Each `entry_plan` row is ``{"classes": [class index, ...], "confirm": bool,
    "stalls": int}`` and produces one rider, one horse and one entry.  Rows keep a
    `by_class` map from class id to the class entry id created on that class.
    """
    ctx = build_approved_show(
        show_overrides=show_overrides,
        division_overrides=division_overrides,
        class_specs=class_specs,
        ring_specs=ring_specs or [{}],
    )
    rows: List[Dict[str, Any]] = []
    for spec in entry_plan:
        rider = create_rider()
        horse = create_horse()
        class_ids = [ctx["class_ids"][index] for index in spec.get("classes", [])]
        row = build_entry(
            ctx["show_id"], rider["id"], horse["id"], class_ids, spec.get("stalls", 0)
        )
        if spec.get("confirm", True):
            settle_entry(row["entry_id"], rider["id"])
            confirm_entry(row["entry_id"])
        row["rider"] = rider
        row["horse"] = horse
        row["by_class"] = dict(zip(class_ids, row["class_entry_ids"]))
        rows.append(row)
    ctx["field"] = rows
    return ctx


def confirmed_rows_for_class(ctx: Dict[str, Any], class_id: str) -> List[str]:
    """Class entry ids on `class_id` that are currently CONFIRMED, in creation order."""
    ids = []
    for row in ctx["field"]:
        ce_id = row.get("by_class", {}).get(class_id)
        if ce_id and get_class_entry(ce_id)["status"] == "CONFIRMED":
            ids.append(ce_id)
    return ids


def stage_class_slot(ctx: Dict[str, Any], class_id: str, start_utc: str) -> Dict[str, Any]:
    """Book one class of a `build_multi_class_show` context and card its officials."""
    if "judge_id" not in ctx:
        ctx.update(build_judge_and_steward())
    slot = book_slot(ctx["ring_id"], class_id, start_utc)
    card_judge_and_steward(slot["id"], ctx["judge_id"], ctx["steward_id"])
    ctx.setdefault("slots", {})[class_id] = slot
    ctx["slot"] = slot
    ctx["slot_id"] = slot["id"]
    return slot


def run_class_to_posted(ctx: Dict[str, Any], class_id: str, actual_minutes: int,
                        place_ids: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Start the staged slot, place its confirmed rows 1..n and post the purse."""
    if not ctx.get("coverage_shift"):
        ctx["coverage_shift"] = build_active_coverage(ctx["show_id"])
    ids = list(place_ids) if place_ids is not None else confirmed_rows_for_class(ctx, class_id)
    start_slot(ctx["slots"][class_id]["id"])
    record_results(class_id, ctx["judge_id"], default_placings(ids), actual_minutes)
    return post_results(class_id)


def build_steward() -> Dict[str, Any]:
    official = create_official(license_roles=["STEWARD"], licensed_disciplines=["JUMPER"])
    return {
        "steward": official,
        "steward_id": official["id"],
        "steward_headers": make_steward_headers(official["id"]),
    }
