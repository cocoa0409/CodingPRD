"""Composite setup helpers.

Each pytest test runs against a freshly-restarted, empty server, so every fixture
builds its preconditions from scratch through PRD-declared endpoints only. Setup calls
use get_success_data() (lenient) so a broken precondition surfaces as a clear failure.

The dominant preamble across the design indices is:
    nonprofit -> nofo -> application(submit, start-review, 3 reviews => SCORED)
    -> award (=> DRAFT subaward) -> budget lines -> activate (=> ACTIVE subaward)
which is encapsulated here so tests carry only their trigger + assertions.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_PERIOD_START,
    DEFAULT_PERIOD_END,
    DEFAULT_BUDGET_LINE,
    DEFAULT_DRAWDOWN_PERIOD_START,
    DEFAULT_DRAWDOWN_PERIOD_END,
)
from .factories import (
    create_nonprofit_payload,
    create_nofo_payload,
    create_application_payload,
    create_review_payload,
    create_drawdown_payload,
    create_monitoring_visit_payload,
)
from .test_users import (
    make_program_officer_headers,
    make_grants_manager_headers,
    make_panelist_headers,
    make_subrecipient_headers,
)

_PANELISTS = ("pan-1", "pan-2", "pan-3")
_DEFAULT_SCORES = (80, 85, 90)


# ─── Primitive builders ───────────────────────────────────────
def create_nonprofit(legal_name="Test Nonprofit", uei=None, ein="11-1111111"):
    payload = create_nonprofit_payload(legal_name=legal_name, ein=ein)
    if uei is not None:
        payload["uei"] = uei
    return get_success_data(api_client.create_nonprofit(payload, make_program_officer_headers()))


def create_nofo(**overrides):
    return get_success_data(
        api_client.create_nofo(create_nofo_payload(**overrides), make_program_officer_headers())
    )


def create_draft_application(nofo_id, np_id, **overrides):
    """File a DRAFT application (POST /nofos/{id}/applications) as the owning subrecipient."""
    payload = create_application_payload(np_id, **overrides)
    return get_success_data(
        api_client.create_application(nofo_id, payload, make_subrecipient_headers(np_id))
    )


def create_scored_application(nofo_id, np_id, scores=_DEFAULT_SCORES, panelists=_PANELISTS,
                              **app_overrides):
    """Drive an application to SCORED: submit -> start-review -> 3 panel reviews.

    The third review auto-transitions UNDER_REVIEW -> SCORED (panel quorum = 3).
    """
    app = create_draft_application(nofo_id, np_id, **app_overrides)
    sub_headers = make_subrecipient_headers(np_id)
    get_success_data(api_client.submit_application(app["id"], sub_headers))
    get_success_data(api_client.start_review(app["id"], make_program_officer_headers()))
    for score, panelist in zip(scores, panelists):
        get_success_data(
            api_client.create_review(
                app["id"], create_review_payload(score), make_panelist_headers(panelist)
            )
        )
    return get_success_data(
        api_client.get_application(app["id"], make_program_officer_headers())
    )


def award_and_get_subaward(app_id):
    """Award a SCORED application and return the created DRAFT subaward."""
    get_success_data(api_client.award_application(app_id, make_program_officer_headers()))
    subs = get_success_data(
        api_client.list_subawards(make_program_officer_headers(), params={"application_id": app_id})
    )
    return subs[0]


def get_subaward(sub_id):
    return get_success_data(api_client.get_subaward(sub_id, make_program_officer_headers()))


def get_nofo(nofo_id):
    return get_success_data(api_client.get_nofo(nofo_id, make_program_officer_headers()))


def get_nonprofit(np_id):
    return get_success_data(api_client.get_nonprofit(np_id, make_program_officer_headers()))


def add_budget_lines(sub_id, lines):
    for line in lines:
        get_success_data(
            api_client.create_budget_line(sub_id, dict(line), make_program_officer_headers())
        )


# ─── Composite state builders ─────────────────────────────────
def setup_draft_subaward(requested_amount_cents=11_000_000, indirect_method="DE_MINIMIS",
                         negotiated_indirect_rate=None, budget_lines=None, nofo_overrides=None,
                         period_start=DEFAULT_PERIOD_START, period_end=DEFAULT_PERIOD_END,
                         np_legal_name="Test Nonprofit"):
    """Full chain to a DRAFT (awarded, not-yet-activated) subaward with budget lines added.

    Pass budget_lines=[] to add no budget lines (for the no-budget-lines activation test);
    the default adds one balanced PERSONNEL line.
    """
    np = create_nonprofit(legal_name=np_legal_name)
    nofo = create_nofo(**(nofo_overrides or {}))
    app_overrides = {
        "requested_amount_cents": requested_amount_cents,
        "indirect_method": indirect_method,
        "proposed_period_start": period_start,
        "proposed_period_end": period_end,
    }
    if negotiated_indirect_rate is not None:
        app_overrides["negotiated_indirect_rate"] = negotiated_indirect_rate
    app = create_scored_application(nofo["id"], np["id"], **app_overrides)
    sub = award_and_get_subaward(app["id"])
    lines = [dict(DEFAULT_BUDGET_LINE)] if budget_lines is None else budget_lines
    add_budget_lines(sub["id"], lines)
    return {
        "nonprofit": np, "nofo": nofo, "application": app, "subaward": sub,
        "np_id": np["id"], "nofo_id": nofo["id"], "app_id": app["id"], "sub_id": sub["id"],
    }


def setup_active_subaward(**kwargs):
    """Full chain to an ACTIVE subaward. Returns ctx with the activated subaward + version."""
    ctx = setup_draft_subaward(**kwargs)
    active = get_success_data(
        api_client.activate_subaward(ctx["sub_id"], make_program_officer_headers())
    )
    ctx["subaward"] = active
    ctx["version"] = active["version"]
    return ctx


def submit_drawdown(sub_id, np_id, requested_amount_cents, expected_version,
                    period_start=DEFAULT_DRAWDOWN_PERIOD_START,
                    period_end=DEFAULT_DRAWDOWN_PERIOD_END):
    payload = create_drawdown_payload(
        requested_amount_cents, expected_version,
        period_covered_start=period_start, period_covered_end=period_end,
    )
    return get_success_data(
        api_client.create_drawdown(sub_id, payload, make_subrecipient_headers(np_id))
    )


def setup_active_subaward_with_drawdown(drawdown_amount=5_000_000, **kwargs):
    """ACTIVE subaward + one SUBMITTED drawdown. Refreshes ctx['version'] post-submit."""
    ctx = setup_active_subaward(**kwargs)
    dd = submit_drawdown(ctx["sub_id"], ctx["np_id"], drawdown_amount, ctx["version"])
    ctx["drawdown"] = dd
    ctx["dd_id"] = dd["id"]
    ctx["version"] = get_subaward(ctx["sub_id"])["version"]
    return ctx


def setup_active_subaward_with_scheduled_visit(scheduled_start="2026-07-10T09:00:00Z",
                                               scheduled_end="2026-07-10T12:00:00Z",
                                               monitor="gm-1", **kwargs):
    """ACTIVE subaward + one SCHEDULED monitoring visit by `monitor`."""
    ctx = setup_active_subaward(**kwargs)
    visit = get_success_data(
        api_client.create_monitoring_visit(
            ctx["sub_id"],
            create_monitoring_visit_payload(scheduled_start, scheduled_end),
            make_grants_manager_headers(monitor),
        )
    )
    ctx["visit"] = visit
    ctx["visit_id"] = visit["id"]
    return ctx


def conduct_visit_with_finding(sub_id, visit_id, severity, monitor="gm-1", outcome="DEFICIENT"):
    """Conduct a visit raising a Finding of the given severity; return the created Finding."""
    payload = {"outcome": outcome, "finding_severity": severity}
    get_success_data(
        api_client.conduct_visit(visit_id, payload, make_grants_manager_headers(monitor))
    )
    findings = get_success_data(
        api_client.list_findings(sub_id, make_grants_manager_headers(monitor))
    )
    return findings[0]
