"""Composite setup helpers (PRD §3).

These encapsulate the multi-step sequences (plan -> participant -> offering ->
enroll -> contribute -> close-enrollment -> batch -> open -> certify ->
run-purchase -> read purchase/share-lot) that nearly every calculation, cascade,
and disposition test must reach. All setup calls go through get_success_data() so
a setup failure raises a clear "Setup step failed" rather than a confusing
assertion later. Identity threading: every Participant-owned call uses
make_participant_headers(participant_id) with the real id (PRD §2.1).

Server restarts before every test (per-test-server isolation), so each helper
builds its preconditions from an empty database using only PRD endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_participant_payload,
    create_plan_payload,
    create_offering_payload,
    create_purchase_period_payload,
    create_enrollment_payload,
    create_contribution_payload,
    run_purchase_payload,
)
from .test_users import (
    make_admin_headers,
    make_officer_headers,
    make_participant_headers,
)

ADMIN = make_admin_headers("admin1")
# Distinct admin id for segregation-of-duties: differs from officer1.
ADMIN2 = make_admin_headers("admin2")
OFFICER = make_officer_headers("officer1")


# ─── Atomic creators ───────────────────────────────────────────────
def create_plan(**overrides) -> dict:
    return get_success_data(
        api_client.create_plan(create_plan_payload(**overrides), ADMIN)
    )


def create_participant(**overrides) -> dict:
    return get_success_data(
        api_client.create_participant(create_participant_payload(**overrides), ADMIN)
    )


def create_offering(plan_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_offering_period(
            create_offering_payload(plan_id, **overrides), ADMIN
        )
    )


def enroll(participant_id, offering_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_enrollment(
            create_enrollment_payload(participant_id, offering_id, **overrides),
            make_participant_headers(participant_id),
        )
    )


def contribute(enrollment_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_contribution(
            create_contribution_payload(enrollment_id, **overrides), ADMIN
        )
    )


def create_purchase_period(offering_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_purchase_period(
            offering_id, create_purchase_period_payload(**overrides), ADMIN
        )
    )


# ─── Lifecycle shortcuts ───────────────────────────────────────────
def close_enrollment(offering_id) -> dict:
    return get_success_data(api_client.close_enrollment(offering_id, ADMIN))


def open_batch(pp_id) -> dict:
    return get_success_data(api_client.open_purchase_period(pp_id, ADMIN))


def certify_batch(pp_id, officer=OFFICER) -> dict:
    return get_success_data(api_client.certify_purchase_period(pp_id, officer))


def run_batch(pp_id, expected_version, admin=ADMIN2) -> dict:
    """Run the buy. Defaults to ADMIN2 so the runner differs from officer1 who
    certifies in these helpers (segregation of duties, PRD §2.9)."""
    return get_success_data(
        api_client.run_purchase(pp_id, run_purchase_payload(expected_version), admin)
    )


# ─── Composite scenarios ───────────────────────────────────────────
def setup_open_offering(plan_overrides=None, offering_overrides=None):
    """A plan + an OPEN offering. Returns (plan, offering)."""
    plan = create_plan(**(plan_overrides or {}))
    offering = create_offering(plan["id"], **(offering_overrides or {}))
    return plan, offering


def setup_enrolled_participant(
    plan_overrides=None, offering_overrides=None,
    rate_pct=10, participant_overrides=None,
):
    """plan + OPEN offering + ACTIVE participant + ENROLLED enrollment.
    Returns (plan, offering, participant, enrollment)."""
    plan, offering = setup_open_offering(plan_overrides, offering_overrides)
    participant = create_participant(**(participant_overrides or {}))
    enrollment = enroll(
        participant["id"], offering["id"], contribution_rate_pct=rate_pct
    )
    return plan, offering, participant, enrollment


def setup_certified_batch(
    plan_overrides=None, offering_overrides=None, batch_overrides=None,
    rate_pct=10, gross_pay_cents=1000000,
):
    """Full chain to a CERTIFIED single batch with one ENROLLED participant that
    has one POSTED contribution. Returns a dict with all created entities plus the
    certified batch's current version under key 'pp_version'."""
    plan, offering, participant, enrollment = setup_enrolled_participant(
        plan_overrides, offering_overrides, rate_pct
    )
    contribute(enrollment["id"], gross_pay_cents=gross_pay_cents)
    close_enrollment(offering["id"])
    batch = create_purchase_period(offering["id"], **(batch_overrides or {}))
    open_batch(batch["id"])
    certified = certify_batch(batch["id"])
    return {
        "plan": plan,
        "offering": offering,
        "participant": participant,
        "enrollment": enrollment,
        "batch": batch,
        "pp_version": certified["version"],
    }


def setup_settled_purchase(
    plan_overrides=None, offering_overrides=None, batch_overrides=None,
    rate_pct=10, gross_pay_cents=1000000,
):
    """Full chain through run-purchase. Returns a dict adding 'purchase' and
    'share_lot' for the participant. Used as the precondition for disposition,
    form-3922, and share-lot tests."""
    ctx = setup_certified_batch(
        plan_overrides, offering_overrides, batch_overrides, rate_pct, gross_pay_cents
    )
    run_batch(ctx["batch"]["id"], ctx["pp_version"])
    purchases, _ = _list(api_client.list_purchases, {"enrollment_id": ctx["enrollment"]["id"]})
    ctx["purchase"] = purchases[0]
    lots, _ = _list(
        api_client.list_share_lots, {"participant_id": ctx["participant"]["id"]},
        headers=make_participant_headers(ctx["participant"]["id"]),
    )
    ctx["share_lot"] = lots[0]
    return ctx


def _list(list_fn, params, headers=ADMIN):
    """Internal: call a list endpoint and return (data, meta)."""
    resp = list_fn(headers, params=params)
    body = resp.json()
    return body["data"], body["meta"]
