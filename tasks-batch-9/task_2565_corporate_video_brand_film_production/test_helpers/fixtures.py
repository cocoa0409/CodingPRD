"""Precondition builders.

Every test starts against an empty database, so every precondition has to be
rebuilt through the public endpoints of §4 — there is no seeding back door. The
functions here are the smallest useful steps ("open a project", "issue a permit")
plus the named chains the workflows of §3 keep asking for ("a confirmed shoot day",
"a QC-passed cut"). Each one validates its own responses, so a test that fails is
failing on its own assertion rather than on a silently broken setup.
"""

from typing import Any, Optional

from prd_bench_local_runner.testing import validate_paginated

from .api_client import ApiClient
from .assertions import created_row, ok_row
from .constants import (
    DECISION_APPROVE,
    DECISION_ISSUE,
    DECISION_REQUEST_CHANGES,
    DEFAULT_CLOCK,
)
from .factories import (
    approve_budget_payload,
    budget_line_payload,
    cancel_payload,
    cert_decision_payload,
    change_order_decision_payload,
    crew_booking_payload,
    crew_member_payload,
    cut_payload,
    deliverable_payload,
    equipment_reservation_payload,
    film_permit_payload,
    handover_payload,
    liability_coi_payload,
    location_payload,
    project_payload,
    release_payload,
    review_decision_payload,
    shoot_day_payload,
    talent_engagement_payload,
)
from .test_users import (
    CLIENT_APPROVER,
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_2,
    COORDINATOR,
    LINE_PRODUCER,
    POST_SUPERVISOR,
)


# ─── The logical clock (PRD §2.5) ──────────────────────────────────────────


def set_clock(api: ApiClient, to_iso8601: str) -> dict:
    """Move the logical clock, which every derived time-dependent value reads."""
    return ok_row(api.set_clock(to_iso8601, headers=COORDINATOR))


def reset_clock(api: ApiClient) -> dict:
    """Put the clock back at the value every run starts from."""
    return set_clock(api, DEFAULT_CLOCK)


# ─── Projects, budget lines, deliverables (PRD §3.1, §3.2) ─────────────────


def open_project(api: ApiClient, **over: Any) -> dict:
    """A `DRAFT` project, which is where every production begins."""
    return created_row(api.create_project(project_payload(**over), headers=LINE_PRODUCER))


def add_budget_line(api: ApiClient, project_id: str, **over: Any) -> dict:
    """One line on the budget top sheet."""
    return created_row(
        api.create_budget_line(budget_line_payload(project_id, **over), headers=LINE_PRODUCER)
    )


def add_deliverable(api: ApiClient, project_id: str, **over: Any) -> dict:
    """One registered deliverable format."""
    return created_row(
        api.create_deliverable(deliverable_payload(project_id, **over), headers=LINE_PRODUCER)
    )


def lock_scope(api: ApiClient, project_id: str) -> dict:
    """Freeze the creative scope, `DRAFT → SCOPED`."""
    return ok_row(api.lock_scope(project_id, headers=LINE_PRODUCER))


def read_project(api: ApiClient, project_id: str) -> dict:
    """A live project read, which recomputes every derived column."""
    return ok_row(api.get_project(project_id, headers=LINE_PRODUCER))


def approve_budget(api: ApiClient, project_id: str, amount_cents: Optional[int] = None) -> dict:
    """The client's sign-off, `SCOPED → IN_PRODUCTION`.

    When no amount is passed the project's own live `provisional_cost_cents` is
    sent, which is the figure the server snapshots anyway.
    """
    if amount_cents is None:
        amount_cents = read_project(api, project_id)["provisional_cost_cents"]
    return ok_row(
        api.approve_budget(project_id, approve_budget_payload(amount_cents), headers=CLIENT_APPROVER)
    )


def scoped_project(api: ApiClient, **over: Any) -> dict:
    """A `SCOPED` project carrying the one deliverable and one line the lock demands.

    PRD §3.1: the lock "requires the project to carry at least one deliverable
    **and** at least one budget line".
    """
    project = open_project(api, **over)
    deliverable = add_deliverable(api, project["id"])
    line = add_budget_line(api, project["id"])
    project = lock_scope(api, project["id"])
    return {"project": project, "deliverable": deliverable, "budget_line": line}


def production_project(api: ApiClient, **over: Any) -> dict:
    """An `IN_PRODUCTION` project with its budget approved and its lines committed."""
    built = scoped_project(api, **over)
    built["project"] = approve_budget(api, built["project"]["id"])
    return built


def project_in_production_only(api: ApiClient, **over: Any) -> str:
    """The id of an `IN_PRODUCTION` project, for tests that need nothing else."""
    return production_project(api, **over)["project"]["id"]


def handover(api: ApiClient, project_id: str, **over: Any) -> dict:
    """Package the archive, `DELIVERED → ARCHIVED`."""
    return ok_row(api.handover(project_id, handover_payload(**over), headers=LINE_PRODUCER))


# ─── Talent (PRD §3.3) ─────────────────────────────────────────────────────


def cast_talent(api: ApiClient, project_id: str, **over: Any) -> dict:
    """A `DRAFT` deal memo priced on the `PROVISIONAL` basis."""
    return created_row(
        api.create_talent_engagement(
            talent_engagement_payload(project_id, **over), headers=LINE_PRODUCER
        )
    )


def cast_union_talent(api: ApiClient, project_id: str, **over: Any) -> dict:
    """A `UNION` deal memo, which the pairing rule forces onto session-and-reuse."""
    over.setdefault("union_affiliation", "UNION")
    over.setdefault("compensation_model", "UNION_SESSION_REUSE")
    return cast_talent(api, project_id, **over)


def confirm_talent(api: ApiClient, engagement_id: str) -> dict:
    """Countersign the memo, `DRAFT → CONFIRMED`, re-pricing on the `FINAL` basis."""
    return ok_row(api.confirm_talent_engagement(engagement_id, headers=LINE_PRODUCER))


# ─── Locations and shoot days (PRD §3.4) ───────────────────────────────────


def register_location(api: ApiClient, **over: Any) -> dict:
    """A scouted venue, which starts at `scouting_status` `SCOUTED`."""
    return created_row(api.create_location(location_payload(**over), headers=COORDINATOR))


def schedule_shoot_day(api: ApiClient, project_id: str, location_id: str, **over: Any) -> dict:
    """A `PLANNED` shoot day occupying one stage of the venue."""
    return created_row(
        api.create_shoot_day(
            shoot_day_payload(project_id, location_id, **over), headers=COORDINATOR
        )
    )


def read_shoot_day(api: ApiClient, shoot_day_id: str) -> dict:
    """A live shoot-day read, which recomputes posture, crew count and day cost."""
    return ok_row(api.get_shoot_day(shoot_day_id, headers=COORDINATOR))


def confirm_shoot_day(api: ApiClient, shoot_day_id: str) -> dict:
    """Lock the day, `PLANNED → CONFIRMED`."""
    return ok_row(api.confirm_shoot_day(shoot_day_id, headers=COORDINATOR))


def publish_call_sheet(api: ApiClient, shoot_day_id: str) -> dict:
    """Publish the call sheet, `call_sheet_status` `DRAFT → PUBLISHED`."""
    return ok_row(api.publish_call_sheet(shoot_day_id, headers=COORDINATOR))


def wrap_shoot_day(api: ApiClient, shoot_day_id: str) -> dict:
    """Wrap the day, `CONFIRMED → WRAPPED`, cascading into its children."""
    return ok_row(api.wrap_shoot_day(shoot_day_id, headers=COORDINATOR))


def cancel_shoot_day(api: ApiClient, shoot_day_id: str, **over: Any) -> dict:
    """Cancel the day, unwinding every commitment it carried."""
    return ok_row(api.cancel_shoot_day(shoot_day_id, cancel_payload(**over), headers=COORDINATOR))


# ─── Compliance paperwork (PRD §3.5) ───────────────────────────────────────


def file_coi(api: ApiClient, project_id: str, **over: Any) -> dict:
    """File a project-wide certificate of insurance, which lands at `SUBMITTED`."""
    return created_row(
        api.create_compliance_cert(liability_coi_payload(project_id, **over), headers=COMPLIANCE_OFFICER)
    )


def file_permit(api: ApiClient, project_id: str, shoot_day_id: str, **over: Any) -> dict:
    """File a film permit for exactly one shooting day."""
    return created_row(
        api.create_compliance_cert(
            film_permit_payload(project_id, shoot_day_id, **over), headers=COMPLIANCE_OFFICER
        )
    )


def decide_cert(api: ApiClient, cert_id: str, decision: str, **over: Any) -> dict:
    """Record the authority's verdict from a second officer.

    PRD §3.5 requires the decision to "come from a different `X-User-ID` than the
    filer's", so the filing helpers above and this one deliberately act as two
    different compliance officers.
    """
    return ok_row(
        api.compliance_cert_decision(
            cert_id, cert_decision_payload(decision, **over), headers=COMPLIANCE_OFFICER_2
        )
    )


def issued_coi(api: ApiClient, project_id: str, **over: Any) -> dict:
    """A certificate of insurance actually in force."""
    cert = file_coi(api, project_id, **over)
    return decide_cert(api, cert["id"], DECISION_ISSUE)


def issued_permit(api: ApiClient, project_id: str, shoot_day_id: str, **over: Any) -> dict:
    """A film permit actually in force for the named day."""
    cert = file_permit(api, project_id, shoot_day_id, **over)
    return decide_cert(api, cert["id"], DECISION_ISSUE)


def read_cert(api: ApiClient, cert_id: str) -> dict:
    """A live certificate read, which derives `effective_status` off the clock."""
    return ok_row(api.get_compliance_cert(cert_id, headers=COMPLIANCE_OFFICER))


# ─── Crew, bookings and kit (PRD §3.6) ─────────────────────────────────────


def add_crew_member(api: ApiClient, **over: Any) -> dict:
    """One roster entry, carrying the rate every booking of that person prices at."""
    return created_row(api.create_crew_member(crew_member_payload(**over), headers=COORDINATOR))


def book_crew(api: ApiClient, shoot_day_id: str, crew_member_id: str, **over: Any) -> dict:
    """A `HELD` booking, inside the provisional figure but not the committed one."""
    return created_row(
        api.create_crew_booking(
            crew_booking_payload(shoot_day_id, crew_member_id, **over), headers=COORDINATOR
        )
    )


def confirm_booking(api: ApiClient, booking_id: str) -> dict:
    """Confirm a booking, `HELD → CONFIRMED`, which commits its cost."""
    return ok_row(api.confirm_crew_booking(booking_id, headers=COORDINATOR))


def release_booking(api: ApiClient, booking_id: str, **over: Any) -> dict:
    """Drop a booking, reversing exactly what it contributed."""
    return ok_row(api.release_crew_booking(booking_id, release_payload(**over), headers=COORDINATOR))


def read_booking(api: ApiClient, booking_id: str) -> dict:
    return ok_row(api.get_crew_booking(booking_id, headers=COORDINATOR))


def reserve_equipment(api: ApiClient, shoot_day_id: str, **over: Any) -> dict:
    """A `RESERVED` kit reservation, which lands on both ledgers at once."""
    return created_row(
        api.create_equipment_reservation(
            equipment_reservation_payload(shoot_day_id, **over), headers=COORDINATOR
        )
    )


# ─── Cuts, QC and the client review loop (PRD §3.8) ────────────────────────


def read_deliverable(api: ApiClient, deliverable_id: str) -> dict:
    """A live deliverable read, which recomputes its four counters."""
    return ok_row(api.get_deliverable(deliverable_id, headers=POST_SUPERVISOR))


def read_cut(api: ApiClient, version_id: str) -> dict:
    return ok_row(api.get_deliverable_version(version_id, headers=POST_SUPERVISOR))


def upload_cut(api: ApiClient, deliverable_id: str, expected_version: int, **over: Any) -> dict:
    """Upload a cut against a stated expectation of the parent's `version`."""
    return created_row(
        api.create_deliverable_version(
            cut_payload(deliverable_id, expected_version, **over), headers=POST_SUPERVISOR
        )
    )


def upload_next_cut(api: ApiClient, deliverable_id: str, **over: Any) -> dict:
    """Upload a cut presenting the parent's current `version`, so the guard passes.

    PRD §2.10 makes `expected_deliverable_version` "the client's last observed
    `version` of the parent deliverable", so reading it first is what an honest
    client does.
    """
    parent = read_deliverable(api, deliverable_id)
    return upload_cut(api, deliverable_id, parent["version"], **over)


def record_qc(api: ApiClient, version_id: str) -> dict:
    """Record the one permitted QC pass, whose verdict the server derives."""
    return ok_row(api.record_qc(version_id, headers=POST_SUPERVISOR))


def submit_cut(api: ApiClient, version_id: str) -> dict:
    """Send a QC-passed cut to the client, `DRAFT → SUBMITTED`."""
    return ok_row(api.submit_version(version_id, headers=POST_SUPERVISOR))


def review_cut(api: ApiClient, version_id: str, decision: str, **over: Any) -> dict:
    """Record the client's verdict from an approver who is not the submitter."""
    return ok_row(
        api.review_decision(
            version_id, review_decision_payload(decision, **over), headers=CLIENT_APPROVER
        )
    )


def passed_cut(api: ApiClient, deliverable_id: str, **over: Any) -> dict:
    """A cut sitting at `review_status` `DRAFT` and `technical_status` `QC_PASSED`."""
    cut = upload_next_cut(api, deliverable_id, **over)
    return record_qc(api, cut["id"])


def submitted_cut(api: ApiClient, deliverable_id: str, **over: Any) -> dict:
    """A cut awaiting the client's decision, with the deliverable at `IN_REVIEW`."""
    cut = passed_cut(api, deliverable_id, **over)
    return submit_cut(api, cut["id"])


def approved_cut(api: ApiClient, deliverable_id: str, **over: Any) -> dict:
    """A cut the client has signed off, taking the deliverable to `APPROVED`."""
    cut = submitted_cut(api, deliverable_id, **over)
    return review_cut(api, cut["id"], DECISION_APPROVE)


def changes_requested_cut(api: ApiClient, deliverable_id: str, **over: Any) -> dict:
    """A cut the client has sent back, taking the deliverable to `CHANGES_REQUESTED`.

    This is the transition that consumes a revision round, and the one that raises
    a change order once the entitlement is spent.
    """
    cut = submitted_cut(api, deliverable_id, **over)
    return review_cut(api, cut["id"], DECISION_REQUEST_CHANGES)


# ─── Change orders (PRD §3.9) ──────────────────────────────────────────────


def list_change_orders(api: ApiClient, deliverable_id: str, **params: Any) -> Any:
    """The only channel through which a cascade-created order can be discovered."""
    return api.list_deliverable_change_orders(deliverable_id, headers=LINE_PRODUCER, **params)


def change_orders_of(api: ApiClient, deliverable_id: str, **params: Any) -> list:
    """The change orders of a deliverable, "newest last" as §4 lists them."""
    rows, _meta = validate_paginated(list_change_orders(api, deliverable_id, **params))
    return rows


def latest_change_order(api: ApiClient, deliverable_id: str) -> dict:
    """The most recently raised order against a deliverable."""
    rows = change_orders_of(api, deliverable_id)
    assert rows, f"no change order was raised against deliverable {deliverable_id}"
    return rows[-1]


def decide_change_order(api: ApiClient, change_order_id: str, decision: str, **over: Any) -> dict:
    """Approve, reject or void an order from someone other than its requester.

    PRD §3.9: "In all three cases the acting `X-User-ID` must differ from
    `requested_by_user_id`, and the decision records `approved_by_user_id` with the
    acting `X-User-ID`." The cascade records the reviewing client approver as
    the requester, so a line producer decides it here.
    """
    return ok_row(
        api.change_order_decision(
            change_order_id, change_order_decision_payload(decision, **over), headers=LINE_PRODUCER
        )
    )


# ─── Named chains ──────────────────────────────────────────────────────────


def compliant_planned_day(api: ApiClient, **over: Any) -> dict:
    """An `IN_PRODUCTION` project with a `PLANNED` day whose paperwork is in force.

    The permit and insurance tests of PRD §3.5 both pass here, so the day's posture
    reads `RESTRICTED` — "both pass but fewer than three crew bookings are
    confirmed" — which is the weakest posture a confirmation accepts.
    """
    built = production_project(api, **over)
    project_id = built["project"]["id"]
    location = register_location(api)
    day = schedule_shoot_day(api, project_id, location["id"])
    coi = issued_coi(api, project_id, coverage_amount_cents=location["insurance_minimum_cents"])
    permit = issued_permit(api, project_id, day["id"])
    built.update({"location": location, "shoot_day": day, "coi": coi, "permit": permit})
    return built


def confirmed_shoot_day(api: ApiClient, **over: Any) -> dict:
    """The same chain with the day locked, `PLANNED → CONFIRMED`."""
    built = compliant_planned_day(api, **over)
    built["shoot_day"] = confirm_shoot_day(api, built["shoot_day"]["id"])
    return built


def crewed_shoot_day(api: ApiClient, crew_size: int = 3, **over: Any) -> dict:
    """A confirmed day carrying `crew_size` confirmed bookings.

    At three the posture crosses from `RESTRICTED` to `OPEN`, which PRD §3.5 makes
    the precondition the call sheet's crew test measures.
    """
    built = confirmed_shoot_day(api, **over)
    day = built["shoot_day"]
    members = []
    bookings = []
    for index in range(crew_size):
        member = add_crew_member(api, full_name=f"Crew Member {index + 1}")
        booking = book_crew(
            api,
            day["id"],
            member["id"],
            department_role=f"Role {index + 1}",
            call_time=day["call_time"],
            wrap_time=day["wrap_time"],
        )
        bookings.append(confirm_booking(api, booking["id"]))
        members.append(member)
    built["shoot_day"] = read_shoot_day(api, day["id"])
    built["crew_members"] = members
    built["crew_bookings"] = bookings
    return built


def in_post_project(api: ApiClient, **over: Any) -> dict:
    """A project bubbled `IN_PRODUCTION → IN_POST` by wrapping its only shoot day.

    PRD §3.7: "Finally the day bubbles up: when no shoot day of the project remains in
    `PLANNED` or `CONFIRMED` and at least one shoot day exists, and the project is
    `IN_PRODUCTION`, the project advances `IN_PRODUCTION → IN_POST`, incrementing its
    `version` and refreshing its `updated_at`."
    """
    built = confirmed_shoot_day(api, **over)
    # Wrap "requires the logical clock to have reached or passed the day's
    # `wrap_time`", so the clock is moved to exactly that instant.
    set_clock(api, built["shoot_day"]["wrap_time"])
    built["shoot_day"] = wrap_shoot_day(api, built["shoot_day"]["id"])
    built["project"] = read_project(api, built["project"]["id"])
    return built


def delivered_project(api: ApiClient, **over: Any) -> dict:
    """A project bubbled `IN_POST → DELIVERED` by the approval of its last cut.

    PRD §3.8: "Then, if that leaves every deliverable of the project in `APPROVED` and
    the project is `IN_POST`, the project advances `IN_POST → DELIVERED`, which in turn
    completes every `CONFIRMED` talent engagement as described in §3.3."
    """
    built = in_post_project(api, **over)
    built["cut"] = approved_cut(api, built["deliverable"]["id"])
    built["deliverable"] = read_deliverable(api, built["deliverable"]["id"])
    built["project"] = read_project(api, built["project"]["id"])
    return built


def archived_project(api: ApiClient, **over: Any) -> dict:
    """A project handed over, `DELIVERED → ARCHIVED`, with its retention clock running."""
    built = delivered_project(api, **over)
    built["project"] = handover(api, built["project"]["id"])
    return built
