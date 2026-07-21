"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server with an empty DB before each test).
Setup calls use get_success_data (lenient) so a broken precondition surfaces as
a clear "Setup failed" rather than an assertion error deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .test_users import (
    TEST_USERS,
    make_field_adjuster_headers,
    make_qa_reviewer_headers,
)
from .factories import (
    create_adjuster_payload,
    create_license_payload,
    create_cat_event_payload,
    create_deployment_payload,
    create_claim_payload,
    create_assignment_payload,
    create_inspection_payload,
    create_estimate_payload,
    create_report_payload,
    create_time_entry_payload,
    create_fee_schedule_payload,
    create_fee_bill_payload,
)

_ADMIN = TEST_USERS["licensing_admin_headers"]
_DESK = TEST_USERS["desk_examiner_headers"]
_BILLING = TEST_USERS["billing_manager_headers"]


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(api, iso_ts, headers=None):
    return get_success_data(api.set_clock({"to_iso8601": iso_ts}, headers or _ADMIN))


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------
def create_adjuster(api, **overrides):
    return get_success_data(api.create_adjuster(create_adjuster_payload(**overrides), _ADMIN))


def create_license(api, adjuster_id, **overrides):
    return get_success_data(api.create_license(create_license_payload(adjuster_id, **overrides), _ADMIN))


def create_active_license(api, adjuster_id, **overrides):
    lic = create_license(api, adjuster_id, **overrides)
    return get_success_data(api.activate_license(lic["id"], _ADMIN))


def create_fee_schedule(api, **overrides):
    return get_success_data(api.create_fee_schedule(create_fee_schedule_payload(**overrides), _BILLING))


def create_claim(api, **overrides):
    return get_success_data(api.create_claim(create_claim_payload(**overrides), _DESK))


def create_cat_event(api, **overrides):
    return get_success_data(api.create_cat_event(create_cat_event_payload(**overrides), _ADMIN))


def create_deployment(api, adjuster_id, cat_event_id, **overrides):
    return get_success_data(
        api.create_deployment(create_deployment_payload(adjuster_id, cat_event_id, **overrides), _ADMIN)
    )


def create_assignment(api, claim_id, adjuster_id, **overrides):
    return get_success_data(
        api.create_assignment(create_assignment_payload(claim_id, adjuster_id, **overrides), _DESK)
    )


def accept_assignment(api, assignment_id, adjuster_id):
    return get_success_data(api.accept_assignment(assignment_id, make_field_adjuster_headers(adjuster_id)))


def create_inspection(api, assignment_id, claim_id, adjuster_id, **overrides):
    return get_success_data(
        api.create_inspection(
            create_inspection_payload(assignment_id, claim_id, **overrides),
            make_field_adjuster_headers(adjuster_id),
        )
    )


def start_inspection(api, inspection_id, adjuster_id):
    return get_success_data(api.start_inspection(inspection_id, make_field_adjuster_headers(adjuster_id)))


def complete_inspection(api, inspection_id, adjuster_id):
    return get_success_data(api.complete_inspection(inspection_id, make_field_adjuster_headers(adjuster_id)))


def create_estimate(api, inspection_id, claim_id, adjuster_id, line_items=None, **overrides):
    return get_success_data(
        api.create_estimate(
            create_estimate_payload(inspection_id, claim_id, line_items=line_items, **overrides),
            make_field_adjuster_headers(adjuster_id),
        )
    )


def approve_estimate(api, estimate_id, adjuster_id):
    return get_success_data(api.approve_estimate(estimate_id, make_field_adjuster_headers(adjuster_id)))


def create_report(api, inspection_id, assignment_id, adjuster_id, **overrides):
    return get_success_data(
        api.create_report(
            create_report_payload(inspection_id, assignment_id, **overrides),
            make_field_adjuster_headers(adjuster_id),
        )
    )


def submit_report(api, report_id, adjuster_id):
    return get_success_data(api.submit_report(report_id, make_field_adjuster_headers(adjuster_id)))


def qa_decision(api, report_id, qa_adjuster_id, decision, qa_notes="ok"):
    return get_success_data(
        api.qa_decision_report(
            report_id, {"decision": decision, "qa_notes": qa_notes},
            make_qa_reviewer_headers(qa_adjuster_id),
        )
    )


def create_time_entry(api, assignment_id, adjuster_id, **overrides):
    return get_success_data(
        api.create_time_entry(
            create_time_entry_payload(assignment_id, **overrides),
            make_field_adjuster_headers(adjuster_id),
        )
    )


def get_assignment_version(api, assignment_id, adjuster_id) -> int:
    data = get_success_data(api.get_assignment(assignment_id, make_field_adjuster_headers(adjuster_id)))
    return data["version"]


def create_fee_bill(api, assignment_id, claim_id, fee_schedule_id, adjuster_id,
                    billing_method="FEE_SCHEDULE", expected_assignment_version=None):
    """Create a fee bill. If expected_assignment_version is None the current
    Assignment.version is fetched immediately before the create (OCC-correct)."""
    if expected_assignment_version is None:
        expected_assignment_version = get_assignment_version(api, assignment_id, adjuster_id)
    return get_success_data(
        api.create_fee_bill(
            create_fee_bill_payload(assignment_id, claim_id, fee_schedule_id,
                                    billing_method, expected_assignment_version),
            make_field_adjuster_headers(adjuster_id),
        )
    )


# --------------------------------------------------------------------------
# Composite scenarios
# --------------------------------------------------------------------------
def setup_accepted_assignment(api, *, loss_state="FL", license_state="FL",
                              peril_type="HAIL", policy_type="ACV", adjuster_type="INDEPENDENT"):
    """Licensed adjuster + claim + assignment accepted (work_status=ACCEPTED).

    Returns a dict of created entities and their ids.
    """
    adj = create_adjuster(api, home_state=license_state, adjuster_type=adjuster_type)
    lic = create_active_license(api, adj["id"], state_code=license_state)
    claim = create_claim(api, loss_state=loss_state, peril_type=peril_type, policy_type=policy_type)
    asg = create_assignment(api, claim["id"], adj["id"])
    accept_assignment(api, asg["id"], adj["id"])
    return {
        "adjuster": adj, "adj_id": adj["id"],
        "license": lic, "lic_id": lic["id"],
        "claim": claim, "claim_id": claim["id"],
        "assignment": asg, "asg_id": asg["id"],
    }


def setup_completed_inspection(api, *, insp_start="2026-07-02T09:00:00Z",
                               insp_end="2026-07-02T10:00:00Z", **kwargs):
    """Accepted assignment + inspection created, started, and completed."""
    ctx = setup_accepted_assignment(api, **kwargs)
    insp = create_inspection(api, ctx["asg_id"], ctx["claim_id"], ctx["adj_id"],
                             scheduled_start=insp_start, scheduled_end=insp_end)
    start_inspection(api, insp["id"], ctx["adj_id"])
    complete_inspection(api, insp["id"], ctx["adj_id"])
    ctx["inspection"] = insp
    ctx["insp_id"] = insp["id"]
    return ctx


def setup_work_complete_assignment(api, *, rcv_line_cents=4_000_000, depreciation_pct=0,
                                   photo_count=2, with_fee_schedule=True, **kwargs):
    """Full chain to work_status=WORK_COMPLETE: accepted assignment, completed
    inspection, an APPROVED estimate (Claim.rcv_cents = rcv_line_cents), and a
    SUBMITTED report. Optionally also creates a canonical fee schedule.
    """
    ctx = setup_completed_inspection(api, **kwargs)
    line_items = [{"description": "Roof", "rcv_cents": rcv_line_cents, "depreciation_pct": depreciation_pct}]
    est = create_estimate(api, ctx["insp_id"], ctx["claim_id"], ctx["adj_id"], line_items=line_items)
    approve_estimate(api, est["id"], ctx["adj_id"])
    rpt = create_report(api, ctx["insp_id"], ctx["asg_id"], ctx["adj_id"], photo_count=photo_count)
    submit_report(api, rpt["id"], ctx["adj_id"])
    ctx["estimate"] = est
    ctx["est_id"] = est["id"]
    ctx["report"] = rpt
    ctx["rpt_id"] = rpt["id"]
    if with_fee_schedule:
        fs = create_fee_schedule(api)
        ctx["fee_schedule"] = fs
        ctx["fs_id"] = fs["id"]
    return ctx


def setup_two_adjusters_report_submitted(api, *, policy_type="ACV", rcv_line_cents=50_000,
                                         depreciation_pct=10, with_fee_schedule=False):
    """Field adjuster A (author, licensed) + distinct QA adjuster B; A's report is
    SUBMITTED (inspection COMPLETED, assignment WORK_COMPLETE, claim UNDER_REVIEW).

    Returns the standard ctx plus 'qa_id' for the QAReviewer.
    """
    ctx = setup_work_complete_assignment(
        api, rcv_line_cents=rcv_line_cents, depreciation_pct=depreciation_pct,
        photo_count=3, with_fee_schedule=with_fee_schedule, policy_type=policy_type,
    )
    qa = create_adjuster(api, adjuster_type="STAFF")
    ctx["qa"] = qa
    ctx["qa_id"] = qa["id"]
    return ctx


def setup_confirmed_deployment(api, *, roster_capacity=3, peril_type="HURRICANE",
                               start_at="2026-07-20T09:00:00Z", end_at="2026-07-20T17:00:00Z"):
    """CatEvent OPEN + one CONFIRMED deployment (roster_filled_count=1)."""
    adj = create_adjuster(api, adjuster_type="CAT")
    ce = create_cat_event(api, peril_type=peril_type, roster_capacity=roster_capacity)
    dep = create_deployment(api, adj["id"], ce["id"], start_at=start_at, end_at=end_at)
    get_success_data(api.confirm_deployment(dep["id"], _ADMIN))
    return {"adj_id": adj["id"], "ce_id": ce["id"], "dep_id": dep["id"],
            "cat_event": ce, "deployment": dep}


def setup_approved_fee_bill_on_settled_claim(api):
    """Single-assignment claim settled by QA approval, with a FEE_SCHEDULE bill in
    APPROVED status. Used for the payment→close cascade.

    Returns ctx with 'bill_id' and 'qa_id'.
    """
    ctx = setup_two_adjusters_report_submitted(
        api, policy_type="RCV", rcv_line_cents=4_000_000, depreciation_pct=0,
        with_fee_schedule=True,
    )
    # QA approve → claim SETTLED
    qa_decision(api, ctx["rpt_id"], ctx["qa_id"], "APPROVED")
    bill = create_fee_bill(api, ctx["asg_id"], ctx["claim_id"], ctx["fs_id"], ctx["adj_id"],
                           billing_method="FEE_SCHEDULE")
    get_success_data(api.submit_fee_bill(bill["id"], make_field_adjuster_headers(ctx["adj_id"])))
    get_success_data(api.approve_fee_bill(bill["id"], _BILLING))
    ctx["bill"] = bill
    ctx["bill_id"] = bill["id"]
    return ctx
