"""Validation precedence: when two checks could both fail on one request, the PRD's
fixed precedence (§2.9) determines the single returned error. State-machine legality
beats business-fiscal; body foreign-key resolution beats business-safety.
"""
from test_helpers import validate_error, get_success_data, ApiErrorId, NON_EXISTENT_UUID
from test_helpers import fixtures as F


CLERK = F.CLERK
OFFICER = F.OFFICER


# ==========================================================================
# Difficulty: priority_pair_validation_conflict / state_vs_fiscal_release_foreclosed_lien_unpaid
# ==========================================================================
def test_release_of_foreclosed_unpaid_lien_returns_invalid_state(api):
    """PRD §2.9: "State-machine legality is then checked: a transition requested from
    a state where it is not defined yields `ERR_INVALID_STATE`. Only after all of
    these pass does the system evaluate the operation's own business constraints
    (substantiation, fee-schedule presence, demolition eligibility, contest windows,
    hearing slots and ripeness, continuance limits, foreclosure ripeness,
    duplicate-lien, nothing-to-lien, optimistic concurrency, balance, missing actual
    cost, duplicate parcel, re-inspection target)."
    PRD §3.12: "Both `RELEASED` and `FORECLOSED` are terminal for a lien."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_release_foreclosed_lien_unpaid
    """
    # MAJOR notice OVERDUE; lien RECORDED with no payment; advance 90+ days; foreclose.
    ctx = F.setup_recorded_lien(
        issue_clock="2026-01-01T00:00:00Z", overdue_clock="2026-01-25T00:00:00Z"
    )
    lien_id = ctx["lien"]["id"]
    F.set_clock("2026-04-26T00:00:00Z")  # >= 90 days from recording (2026-01-25)
    foreclosed = get_success_data(api.foreclose_lien(lien_id, CLERK))
    assert foreclosed["status"] == "FORECLOSED", (
        f"setup expected FORECLOSED, got {foreclosed['status']}"
    )

    # Release is undefined from FORECLOSED (state) AND the lien is unpaid (fiscal);
    # state precedence wins -> ERR_INVALID_STATE.
    resp = api.release_lien(lien_id, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_release_unpaid_recorded_lien_surfaces_fiscal_error(api):
    """PRD §3.12: "A `RECORDED` lien is released by a finance clerk once it is paid
    in full — that is, once the case's `payments_applied_cents` is at least the
    lien's `total_cents`; an attempt to release with the lien not yet covered is
    rejected with `ERR_BALANCE_OUTSTANDING`."

    With the lien still RECORDED (release IS a defined transition), only the fiscal
    check can fail, isolating the lower-precedence error the foreclosed case
    pre-empts.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_release_foreclosed_lien_unpaid
    """
    ctx = F.setup_recorded_lien(
        issue_clock="2026-01-01T00:00:00Z", overdue_clock="2026-01-25T00:00:00Z"
    )
    # Lien is RECORDED and unpaid; the state check passes, the fiscal check fails.
    resp = api.release_lien(ctx["lien"]["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_BALANCE_OUTSTANDING.value)


# ==========================================================================
# Difficulty: priority_pair_validation_conflict / safety_vs_reference_demolition_bad_property
# ==========================================================================
def test_demolition_with_nonexistent_case_returns_reference_not_found(api):
    """PRD §2.9: "Body foreign-key resolution follows, yielding
    `ERR_REFERENCE_NOT_FOUND` ... Only after all of these pass does the system
    evaluate the operation's own business constraints (... demolition eligibility
    ...)."
    PRD §2.8: "When a create request names a parent or related resource — an
    `owner_id`, a `property_id`, a `case_id`, a `source_inspection_id`, or a
    `notice_id` — and that reference does not resolve to an existing record, the
    request is rejected with `ERR_REFERENCE_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_reference_demolition_bad_property
    """
    F.set_clock("2026-01-01T00:00:00Z")
    payload = {
        "case_id": NON_EXISTENT_UUID,
        "action_kind": "DEMOLITION",
        "estimated_cost_cents": 100000,
    }
    resp = api.create_abatement_order(payload, OFFICER)
    # Reference resolution (priority 5) precedes the safety check (priority 9).
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


def test_demolition_on_resolving_occupied_case_surfaces_safety_error(api):
    """PRD §3.11: "ordering a `DEMOLITION` requires that the property's `occupancy`
    be `VACANT` and that the case carry a `HAZARD`-class notice in either `OVERDUE`
    or `UPHELD` status; otherwise the order is rejected with
    `ERR_DEMOLITION_NOT_PERMITTED`."

    With a resolving case_id, the body-FK check passes, isolating the
    lower-precedence safety error that the bad-reference case pre-empts.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_reference_demolition_bad_property
    """
    # OCCUPIED property with a HAZARD notice OVERDUE: the case_id resolves, so only
    # the demolition-eligibility (safety) check can fail.
    ctx = F.setup_issued_notice("HAZARD", occupancy="OCCUPIED", clock="2026-01-01T00:00:00Z")
    F.set_clock("2026-01-20T00:00:00Z")  # HAZARD cure 7 -> OVERDUE
    resp = api.create_abatement_order(
        {
            "case_id": ctx["case"]["id"],
            "action_kind": "DEMOLITION",
            "estimated_cost_cents": 100000,
        },
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_DEMOLITION_NOT_PERMITTED.value)
