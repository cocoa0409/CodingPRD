"""Chronic-nuisance / abatement: the two independent parcel axes, the dismissal
downgrade-and-vacate cascade, violation-count conservation, escalation deadline, and
the abatement-create OCC guard (queue A depth + queue B corner)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    code_officer_headers,
)
from test_helpers import fixtures as fx


def _designated_with_scheduled_hearing_on_third(api):
    ctx = fx.setup_designated_property(api, zoning="RESIDENTIAL")
    e3 = ctx["enforcements"][2]
    assert e3["tier"] == "CITATION"
    fx.contest(api, e3["id"])
    hearing = fx.schedule_hearing(api, e3["id"], "2026-05-20T10:00:00Z", "hof-9")
    return ctx, e3, hearing


# --- Two independent parcel axes (queue A) ---

def test_comply_abates_without_clearing_chronic_designation(api):
    """PRD §3.4: "The `chronic_status` axis moves `NONE → WATCH → DESIGNATED` ... The
    `abatement_status` axis — `NONE`, `UNDER_ABATEMENT`, `ABATED` — is driven separately by the
    abatement-order lifecycle. The two axes evolve independently."
    PRD §3.8: comply "on success moves the parcel to `ABATED` and increments its `version`."

    Design: Difficulty/non_linear_state_machine/property_parallel_chronic_and_abatement_axes
    """
    ctx = fx.setup_designated_property(api, zoning="RESIDENTIAL")
    validate_success(api.comply_abatement_order(ctx["abatement_id"], code_officer_headers()), 200)
    prop = fx.read_property(api, ctx["prop_id"])
    assert prop["abatement_status"] == "ABATED"
    assert prop["chronic_status"] == "DESIGNATED"


def test_comply_moves_order_to_complied(api):
    """PRD §3.8: "A `CodeOfficer` marks compliance, moving the order `PENDING → COMPLIED`; this
    requires the parcel's `abatement_status` to be `UNDER_ABATEMENT`, else
    `ERR_PROPERTY_NOT_UNDER_ABATEMENT`, and on success moves the parcel to `ABATED`".

    Design: Difficulty/non_linear_state_machine/property_parallel_chronic_and_abatement_axes
    """
    ctx = fx.setup_designated_property(api, zoning="RESIDENTIAL")
    order = validate_success(api.comply_abatement_order(ctx["abatement_id"], code_officer_headers()), 200)
    assert order["status"] == "COMPLIED"
    prop = fx.read_property(api, ctx["prop_id"])
    assert prop["chronic_status"] == "DESIGNATED"


# --- Dismissal downgrade-and-vacate cascade, depth 3 (queue A) ---

def test_dismiss_downgrades_chronic_to_watch(api):
    """PRD §3.6: "Because the citation is now dismissed, the parcel's
    `substantiated_violation_count` is decremented and its `chronic_status` recomputed".
    PRD §3.6: "A **`DISMISSED`** decision sets the hearing `PENDING → DISMISSED` and the
    enforcement `HEARING_SCHEDULED → DISMISSED`".

    Design: Difficulty/transitive_cascade/dismiss_downgrade_vacate_cascade_depth3
    """
    ctx, e3, hearing = _designated_with_scheduled_hearing_on_third(api)
    fx.decide(api, hearing["id"], "DISMISSED", deciding_user_id="hof-9")
    enf = fx.read_enforcement(api, e3["id"])
    assert enf["status"] == "DISMISSED"
    prop = fx.read_property(api, ctx["prop_id"])
    assert prop["substantiated_violation_count"] == 2
    assert prop["chronic_status"] == "WATCH"


def test_dismiss_vacates_auto_created_abatement_order(api):
    """PRD §3.6: "if the count falls below the designation threshold and a `PENDING` abatement
    order with `trigger_source` `CHRONIC_DESIGNATION` exists for the parcel, that order is set
    to `VACATED` and the parcel's `abatement_status` returns to `NONE`."

    Design: Difficulty/transitive_cascade/dismiss_downgrade_vacate_cascade_depth3
    """
    ctx, e3, hearing = _designated_with_scheduled_hearing_on_third(api)
    fx.decide(api, hearing["id"], "DISMISSED", deciding_user_id="hof-9")
    order = validate_success(api.get_abatement_order(ctx["abatement_id"], code_officer_headers()), 200)
    assert order["status"] == "VACATED"
    prop = fx.read_property(api, ctx["prop_id"])
    assert prop["abatement_status"] == "NONE"


# --- Violation-count conservation (queue A) ---

def test_violation_count_is_three_before_dismiss(api):
    """PRD §3.4: "The recompute counts the parcel's non-dismissed enforcements within the same
    365-day rolling window and sets the count into `substantiated_violation_count`".

    Design: Difficulty/compensating_invariant/property_violation_count_conservation_on_dismiss
    """
    ctx, e3, hearing = _designated_with_scheduled_hearing_on_third(api)
    prop = fx.read_property(api, ctx["prop_id"])
    assert prop["substantiated_violation_count"] == 3


def test_violation_count_restored_to_two_after_dismiss(api):
    """PRD §3.6: "Because the citation is now dismissed, the parcel's
    `substantiated_violation_count` is decremented and its `chronic_status` recomputed".

    Design: Difficulty/compensating_invariant/property_violation_count_conservation_on_dismiss
    """
    ctx, e3, hearing = _designated_with_scheduled_hearing_on_third(api)
    fx.decide(api, hearing["id"], "DISMISSED", deciding_user_id="hof-9")
    enf = fx.read_enforcement(api, e3["id"])
    assert enf["status"] == "DISMISSED"
    prop = fx.read_property(api, ctx["prop_id"])
    assert prop["substantiated_violation_count"] == 2


# --- Escalation deadline + OCC (queue B) ---

def test_escalate_before_deadline_rejected(api):
    """PRD §3.8: "escalation is permitted only when the current clock is at or after the
    `compliance_deadline`, and an earlier attempt is rejected with
    `ERR_ABATEMENT_DEADLINE_NOT_REACHED`."

    Design: Corner/state_machines/escalate_before_deadline_rejected
    """
    prop = validate_success(api.create_property(
        {"address": "106 Main St", "zoning_type": "COMMERCIAL"}, code_officer_headers()), 201)
    order = validate_success(api.create_abatement_order(
        {"property_id": prop["id"], "expected_property_version": prop["version"],
         "compliance_deadline": "2026-09-01T00:00:00Z"}, code_officer_headers()), 201)
    resp = api.escalate_abatement_order(order["id"], code_officer_headers())
    validate_error(resp, ApiErrorId.ERR_ABATEMENT_DEADLINE_NOT_REACHED.value)


def test_stale_property_version_manual_abatement_rejected(api):
    """PRD §2.8: "Opening a **manual** abatement order requires the request to carry
    `expected_property_version` ... If a substantiate or dismiss cascade has since changed the
    property's `chronic_status` or `substantiated_violation_count` and bumped its `version`, the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412)".
    PRD §3.8: a manual order "moves the parcel to `UNDER_ABATEMENT`, and increments the parcel's `version`."

    Design: Corner/cross_cutting/abatement_occ_stale_property_version
    """
    prop = validate_success(api.create_property(
        {"address": "123 Main St", "zoning_type": "COMMERCIAL"}, code_officer_headers()), 201)
    pv = prop["version"]
    validate_success(api.create_abatement_order(
        {"property_id": prop["id"], "expected_property_version": pv}, code_officer_headers()), 201)
    resp = api.create_abatement_order(
        {"property_id": prop["id"], "expected_property_version": pv}, code_officer_headers())
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
