"""Composite setup helpers.

Every test starts against an empty database, so each helper below builds its
whole precondition chain through published endpoints. The two chains most of
the suite rests on are:

* the **applied** chain — operator, mine site, and a permit sitting in
  ``APPLICATION_SUBMITTED`` with no bond determination yet;
* the **issued** chain — the applied chain plus an accepted third-party cost
  estimate, an accepted bond instrument covering the determination, and a
  ``PermitReviewer`` issuance decision.

All helpers use the lenient success reader so a broken precondition surfaces as
a setup failure rather than as a confusing assertion mismatch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_bond_instrument_payload,
    create_collateral_instrument_payload,
    create_estimate_payload,
    create_forfeiture_proceeding_payload,
    create_inspection_payload,
    create_inspector_profile_payload,
    create_mine_site_payload,
    create_operator_payload,
    create_permit_payload,
    create_permit_revision_payload,
    create_release_application_payload,
    create_self_bond_instrument_payload,
    create_surety_instrument_payload,
    create_violation_notice_payload,
    nominate_legacy_payload,
)
from .test_users import (
    BOND_SPECIALIST_ACCEPTER,
    BOND_SPECIALIST_DECIDER,
    PERMIT_REVIEWER,
    PROGRAM_DIRECTOR,
    PUBLIC_PARTICIPANT,
    make_inspector_headers,
    make_operator_headers,
)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(current_utc: str, headers=None) -> dict:
    """Move the logical clock every temporal rule reads."""
    return get_success_data(api.set_clock(current_utc, headers or PROGRAM_DIRECTOR))


# ---------------------------------------------------------------------------
# Tier 1 — single register rows
# ---------------------------------------------------------------------------
def register_operator(**overrides) -> dict:
    return get_success_data(
        api.create_operator(create_operator_payload(**overrides), PROGRAM_DIRECTOR)
    )


def register_mine_site(**overrides) -> dict:
    return get_success_data(
        api.create_mine_site(create_mine_site_payload(**overrides), PROGRAM_DIRECTOR)
    )


def register_inspector(**overrides) -> dict:
    return get_success_data(
        api.create_inspector_profile(
            create_inspector_profile_payload(**overrides), PROGRAM_DIRECTOR
        )
    )


def register_qualified_operator(**overrides) -> dict:
    """Register an operator and run its elected self-bonding financial test."""
    operator = register_operator(**overrides)
    return get_success_data(
        api.run_financial_test(operator["id"], BOND_SPECIALIST_ACCEPTER)
    )


def refresh_permit(permit_id: str) -> dict:
    return get_success_data(api.get_permit(permit_id, PERMIT_REVIEWER))


def refresh_operator(operator_id: str) -> dict:
    return get_success_data(api.get_operator(operator_id, PROGRAM_DIRECTOR))


def refresh_instrument(instrument_id: str) -> dict:
    return get_success_data(api.get_bond_instrument(instrument_id, PERMIT_REVIEWER))


def refresh_application(application_id: str) -> dict:
    return get_success_data(
        api.get_release_application(application_id, PERMIT_REVIEWER)
    )


def refresh_notice(notice_id: str) -> dict:
    return get_success_data(api.get_violation_notice(notice_id, PROGRAM_DIRECTOR))


def refresh_revision(revision_id: str) -> dict:
    return get_success_data(api.get_permit_revision(revision_id, PERMIT_REVIEWER))


def refresh_proceeding(proceeding_id: str) -> dict:
    return get_success_data(
        api.get_forfeiture_proceeding(proceeding_id, PROGRAM_DIRECTOR)
    )


def refresh_inspection(inspection_id: str) -> dict:
    return get_success_data(api.get_inspection(inspection_id, PROGRAM_DIRECTOR))


def refresh_mine_site(site_id: str) -> dict:
    return get_success_data(api.get_mine_site(site_id, PROGRAM_DIRECTOR))


# ---------------------------------------------------------------------------
# Tier 2 — the applied chain
# ---------------------------------------------------------------------------
def chain_applied(
    *,
    operator=None,
    site=None,
    mining_plan_acres=120.00,
    operator_overrides=None,
    site_overrides=None,
    permit_overrides=None,
) -> dict:
    """Operator + mine site + a permit in APPLICATION_SUBMITTED."""
    operator = operator or register_operator(**(operator_overrides or {}))
    site = site or register_mine_site(**(site_overrides or {}))
    operator_headers = make_operator_headers(operator["id"])
    payload = create_permit_payload(
        site["id"], operator["id"], mining_plan_acres=mining_plan_acres,
        **(permit_overrides or {}),
    )
    permit = get_success_data(api.create_permit(payload, operator_headers))
    return {
        "operator": operator,
        "site": site,
        "permit": permit,
        "operator_headers": operator_headers,
    }


def file_estimate(permit_id, operator_headers, **overrides) -> dict:
    return get_success_data(
        api.create_estimate(create_estimate_payload(permit_id, **overrides), operator_headers)
    )


def accept_estimate(estimate_id, permit_id, headers=None) -> dict:
    """Re-read the permit's version, then accept with that fresh guard value."""
    version = refresh_permit(permit_id)["version"]
    return get_success_data(
        api.accept_estimate(
            estimate_id, {"expected_permit_version": version}, headers or PERMIT_REVIEWER
        )
    )


def chain_estimate_accepted(
    *,
    mining_plan_acres=120.00,
    direct_cost_per_acre=6000.00,
    estimate_effective_date="2026-07-01",
    estimate_overrides=None,
    **chain_kwargs,
) -> dict:
    """The applied chain plus one ACCEPTED third-party cost estimate."""
    ctx = chain_applied(mining_plan_acres=mining_plan_acres, **chain_kwargs)
    estimate = file_estimate(
        ctx["permit"]["id"], ctx["operator_headers"],
        direct_cost_per_acre=direct_cost_per_acre,
        estimate_effective_date=estimate_effective_date,
        **(estimate_overrides or {}),
    )
    ctx["estimate"] = accept_estimate(estimate["id"], ctx["permit"]["id"])
    ctx["permit"] = refresh_permit(ctx["permit"]["id"])
    return ctx


def propose_instrument(
    permit_id, operator_headers, instrument_type="CASH", face_amount=900000.00, **overrides
) -> dict:
    """Propose a bond instrument of any of the four declared types."""
    if instrument_type == "SURETY":
        payload = create_surety_instrument_payload(
            permit_id, face_amount=face_amount, **overrides
        )
    elif instrument_type == "COLLATERAL":
        payload = create_collateral_instrument_payload(
            permit_id, face_amount=face_amount, **overrides
        )
    elif instrument_type == "SELF_BOND":
        payload = create_self_bond_instrument_payload(
            permit_id, face_amount=face_amount, **overrides
        )
    else:
        payload = create_bond_instrument_payload(
            permit_id, face_amount=face_amount, **overrides
        )
    return get_success_data(api.create_bond_instrument(payload, operator_headers))


def accept_instrument(instrument_id, headers=None) -> dict:
    return get_success_data(
        api.accept_bond_instrument(instrument_id, headers or BOND_SPECIALIST_ACCEPTER)
    )


def chain_bond_posted(
    *,
    instrument_type="CASH",
    face_amount=900000.00,
    instrument_overrides=None,
    accepter_headers=None,
    **chain_kwargs,
) -> dict:
    """Accepted estimate plus one ACCEPTED bond instrument, still unissued."""
    ctx = chain_estimate_accepted(**chain_kwargs)
    proposed = propose_instrument(
        ctx["permit"]["id"], ctx["operator_headers"],
        instrument_type=instrument_type, face_amount=face_amount,
        **(instrument_overrides or {}),
    )
    ctx["instrument"] = accept_instrument(proposed["id"], accepter_headers)
    ctx["permit"] = refresh_permit(ctx["permit"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — the issued chain and its lifecycle shortcuts
# ---------------------------------------------------------------------------
def chain_issued(*, disturbed_acres=None, reclaimed_acres_credited=None, **kwargs) -> dict:
    """Full path to an ISSUED permit, optionally with reported disturbance."""
    ctx = chain_bond_posted(**kwargs)
    get_success_data(
        api.decide_permit(ctx["permit"]["id"], {"decision": "ISSUE"}, PERMIT_REVIEWER)
    )
    if disturbed_acres is not None or reclaimed_acres_credited is not None:
        report = {}
        if disturbed_acres is not None:
            report["disturbed_acres"] = disturbed_acres
        if reclaimed_acres_credited is not None:
            report["reclaimed_acres_credited"] = reclaimed_acres_credited
        get_success_data(
            api.report_disturbance(ctx["permit"]["id"], report, ctx["operator_headers"])
        )
    ctx["permit"] = refresh_permit(ctx["permit"]["id"])
    return ctx


def enter_reclamation_phase(ctx) -> dict:
    """Declare the end of active mining, moving the permit to RECLAMATION_PHASE."""
    get_success_data(api.cease_mining(ctx["permit"]["id"], ctx["operator_headers"]))
    ctx["permit"] = refresh_permit(ctx["permit"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — bond release applications
# ---------------------------------------------------------------------------
def file_release_application(ctx, phase="PHASE_I", acres_requested=30.00, **overrides) -> dict:
    return get_success_data(
        api.create_release_application(
            create_release_application_payload(
                ctx["permit"]["id"], phase=phase,
                acres_requested=acres_requested, **overrides,
            ),
            ctx["operator_headers"],
        )
    )


def publish_release_notice(application_id, headers=None) -> dict:
    return get_success_data(
        api.publish_notice(application_id, headers or BOND_SPECIALIST_ACCEPTER)
    )


def setup_release_under_notice(
    *,
    phase="PHASE_I",
    acres_requested=30.00,
    disturbed_acres=120.00,
    **kwargs,
) -> dict:
    """Issued permit with reported disturbance and one PUBLIC_NOTICE application."""
    ctx = chain_issued(disturbed_acres=disturbed_acres, **kwargs)
    application = file_release_application(
        ctx, phase=phase, acres_requested=acres_requested
    )
    ctx["application"] = publish_release_notice(application["id"])
    ctx["permit"] = refresh_permit(ctx["permit"]["id"])
    return ctx


def schedule_release_inspection(
    ctx, *, scheduled_start="2026-08-20T09:00:00Z", duration_hours=4,
    inspector=None, inspection_type="RELEASE",
) -> dict:
    """Book an inspection on the permit and remember its inspector headers."""
    inspector = inspector or ctx.get("inspector") or register_inspector()
    ctx["inspector"] = inspector
    ctx["inspector_headers"] = make_inspector_headers(inspector["id"])
    inspection = get_success_data(
        api.create_inspection(
            create_inspection_payload(
                ctx["permit"]["id"], inspector["id"],
                inspection_type=inspection_type,
                scheduled_start=scheduled_start,
                duration_hours=duration_hours,
            ),
            PROGRAM_DIRECTOR,
        )
    )
    ctx["inspection"] = inspection
    return inspection


def record_inspection_result(ctx, inspection_id, result="PASS", findings_note=None) -> dict:
    note = findings_note or (
        "Phase standards met on the claimed acreage."
        if result == "PASS"
        else "Sediment pond breached; spoil placed outside the permit boundary."
    )
    return get_success_data(
        api.record_inspection_result(
            inspection_id, {"result": result, "findings_note": note},
            ctx["inspector_headers"],
        )
    )


def setup_release_ready_for_decision(
    *,
    phase="PHASE_I",
    acres_requested=30.00,
    disturbed_acres=120.00,
    decision_clock="2026-09-05T00:00:00Z",
    inspection_result="PASS",
    **kwargs,
) -> dict:
    """A published application whose notice period has run and whose RELEASE
    inspection is COMPLETED, so only the decision itself remains."""
    ctx = setup_release_under_notice(
        phase=phase, acres_requested=acres_requested,
        disturbed_acres=disturbed_acres, **kwargs,
    )
    inspection = schedule_release_inspection(ctx)
    if decision_clock:
        set_clock(decision_clock)
    ctx["inspection"] = record_inspection_result(
        ctx, inspection["id"], result=inspection_result
    )
    ctx["application"] = refresh_application(ctx["application"]["id"])
    ctx["permit"] = refresh_permit(ctx["permit"]["id"])
    return ctx


def decide_release(ctx, decision="APPROVE", headers=None, **extra) -> dict:
    payload = {"decision": decision, "inspection_id": ctx["inspection"]["id"]}
    payload.update(extra)
    return get_success_data(
        api.decide_release_application(
            ctx["application"]["id"], payload, headers or BOND_SPECIALIST_DECIDER
        )
    )


def setup_approved_release(**kwargs) -> dict:
    """Carry a phase release all the way through an APPROVE decision."""
    ctx = setup_release_ready_for_decision(**kwargs)
    ctx["application"] = decide_release(ctx, "APPROVE")
    ctx["permit"] = refresh_permit(ctx["permit"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — inspections, notices and penalties
# ---------------------------------------------------------------------------
def setup_completed_violation_inspection(
    ctx, *, scheduled_start="2026-08-03T09:00:00Z", duration_hours=3, inspector=None
) -> dict:
    """A COMPLETED inspection whose result is VIOLATIONS_FOUND."""
    inspection = schedule_release_inspection(
        ctx, scheduled_start=scheduled_start, duration_hours=duration_hours,
        inspector=inspector, inspection_type="ROUTINE",
    )
    ctx["inspection"] = record_inspection_result(
        ctx, inspection["id"], result="VIOLATIONS_FOUND"
    )
    return ctx["inspection"]


def issue_violation_notice(ctx, **overrides) -> dict:
    return get_success_data(
        api.create_violation_notice(
            create_violation_notice_payload(ctx["inspection"]["id"], **overrides),
            ctx["inspector_headers"],
        )
    )


def setup_violation_notice(ctx, *, inspection_overrides=None, **notice_overrides) -> dict:
    """Complete an inspection with violations and issue the notice from it."""
    setup_completed_violation_inspection(ctx, **(inspection_overrides or {}))
    ctx["notice"] = issue_violation_notice(ctx, **notice_overrides)
    ctx["permit"] = refresh_permit(ctx["permit"]["id"])
    return ctx["notice"]


def assess_penalty(notice_id, good_faith_level="RAPID") -> dict:
    return get_success_data(
        api.assess_penalty(
            notice_id, {"good_faith_level": good_faith_level}, PROGRAM_DIRECTOR
        )
    )


def setup_assessed_penalty(ctx, *, good_faith_level="RAPID", **notice_overrides) -> dict:
    """An issued notice carrying an ASSESSED civil penalty."""
    notice = setup_violation_notice(ctx, **notice_overrides)
    ctx["notice"] = assess_penalty(notice["id"], good_faith_level)
    return ctx["notice"]


def order_cessation(ctx, notice_id, reason=None) -> dict:
    return get_success_data(
        api.order_cessation(
            notice_id,
            {"cessation_reason": reason
             or "Cumulative point total reached the cessation threshold."},
            ctx["inspector_headers"],
        )
    )


# ---------------------------------------------------------------------------
# Tier 4 — postures reached without moving money
# ---------------------------------------------------------------------------
def file_permit_revision(ctx, revision_type="EXPANSION", **overrides) -> dict:
    return get_success_data(
        api.create_permit_revision(
            create_permit_revision_payload(
                ctx["permit"]["id"], revision_type=revision_type, **overrides
            ),
            ctx["operator_headers"],
        )
    )


def setup_bond_deficient_by_expansion(*, acreage_delta=60.00, **kwargs) -> dict:
    """Approve an EXPANSION revision so the enlarged plan outruns the held bond.

    This is the cleanest route into BOND_DEFICIENT: no instrument is touched, so
    ``bond_held_amount`` is unchanged while ``bond_required_amount`` rises.
    """
    ctx = kwargs.pop("ctx", None) or chain_issued(**kwargs)
    revision = file_permit_revision(ctx, "EXPANSION", acreage_delta=acreage_delta)
    ctx["revision"] = get_success_data(
        api.decide_permit_revision(
            revision["id"], {"decision": "APPROVE"}, PERMIT_REVIEWER
        )
    )
    ctx["permit"] = refresh_permit(ctx["permit"]["id"])
    return ctx


def initiate_forfeiture(ctx, initiation_reason="BOND_DEFICIENCY_UNCURED") -> dict:
    proceeding = get_success_data(
        api.create_forfeiture_proceeding(
            create_forfeiture_proceeding_payload(
                ctx["permit"]["id"], initiation_reason=initiation_reason
            ),
            PROGRAM_DIRECTOR,
        )
    )
    ctx["proceeding"] = proceeding
    ctx["permit"] = refresh_permit(ctx["permit"]["id"])
    return proceeding


def finalize_forfeiture(ctx, state_reclamation_cost_estimate=1200000.00) -> dict:
    ctx["proceeding"] = get_success_data(
        api.finalize_forfeiture(
            ctx["proceeding"]["id"],
            {"state_reclamation_cost_estimate": state_reclamation_cost_estimate},
            PROGRAM_DIRECTOR,
        )
    )
    ctx["permit"] = refresh_permit(ctx["permit"]["id"])
    return ctx["proceeding"]


# ---------------------------------------------------------------------------
# Tier 5 — legacy inventory
# ---------------------------------------------------------------------------
def register_legacy_site(**overrides) -> dict:
    overrides.setdefault("site_class", "ABANDONED_LEGACY")
    return register_mine_site(**overrides)


def nominate_legacy_site(site_id, **overrides) -> dict:
    return get_success_data(
        api.nominate_legacy_site(
            site_id, nominate_legacy_payload(**overrides), PROGRAM_DIRECTOR
        )
    )


def setup_nominated_legacy_site(*, site_overrides=None, **nomination) -> dict:
    site = register_legacy_site(**(site_overrides or {}))
    return nominate_legacy_site(site["id"], **nomination)


def file_public_comment(application_id, comment_text, is_objection=False) -> dict:
    return get_success_data(
        api.file_public_comment(
            application_id,
            {"comment_text": comment_text, "is_objection": is_objection},
            PUBLIC_PARTICIPANT,
        )
    )
