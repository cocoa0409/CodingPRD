"""The lien pipeline: notice, cure window, maturation, and the dual-variant lien."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, CANONICAL,
    make_platform_admin_headers, make_facility_operator_headers, make_tenant_headers,
    create_facility, create_tenant, create_unit, create_lien_notice,
    setup_matured_unit, set_clock,
)

ADMIN = make_platform_admin_headers()


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / lien_provisional_vs_final_diverge
# ---------------------------------------------------------------------------
def test_provisional_lien_pinned_at_notice_creation(api):
    """PRD §3.2: "For the provisional variant computed at notice creation, the
    number of accrued days is exactly the fourteen-day cure period, projecting the
    accrual through the cure deadline. The result is written to the unit's
    `lien_amount_provisional_cents`, and the notice's `lien_amount_cents` is set to
    this provisional figure."

    Design: Difficulty/dual_variant_calc/lien_provisional_vs_final_diverge
    """
    facility = create_facility(api)
    tenant = create_tenant(api, facility["id"])
    unit = create_unit(api, facility["id"], tenant["id"])
    notice = create_lien_notice(api, unit["id"], facility["id"])
    unit_after = validate_success(api.get_unit(unit["id"], ADMIN))
    notice_after = validate_success(api.get_lien_notice(notice["id"], ADMIN))
    assert unit_after["lien_amount_provisional_cents"] == CANONICAL["provisional_lien_cents"]
    assert notice_after["lien_amount_cents"] == CANONICAL["provisional_lien_cents"]


def test_final_lien_diverges_from_provisional_at_maturation(api):
    """PRD §3.2: "Maturation moves the notice from `SENT` to `MATURED` and recomputes
    the lien to its final variant: the same formula applies, but the number of
    accrued days is the whole number of elapsed days from `notice_sent_at` to the
    maturation instant, obtained by taking the elapsed time and flooring it to whole
    days."
    PRD §3.2: "The result is written to the unit's `lien_amount_final_cents`, and the
    notice's `lien_amount_cents` is updated to this final figure."

    Design: Difficulty/dual_variant_calc/lien_provisional_vs_final_diverge
    """
    ctx = setup_matured_unit(api)  # notice at 2026-03-01, matured at 2026-03-20 (19 elapsed days)
    unit_after = validate_success(api.get_unit(ctx["unit_id"], ADMIN))
    notice_after = validate_success(api.get_lien_notice(ctx["notice_id"], ADMIN))
    assert unit_after["lien_amount_provisional_cents"] == CANONICAL["provisional_lien_cents"]
    assert unit_after["lien_amount_final_cents"] == CANONICAL["final_lien_cents"]
    assert notice_after["lien_amount_cents"] == CANONICAL["final_lien_cents"]
    assert unit_after["lien_amount_final_cents"] != unit_after["lien_amount_provisional_cents"]


# ---------------------------------------------------------------------------
# Corner: state and temporal guards on the lien lifecycle
# ---------------------------------------------------------------------------
def test_mature_already_cured_notice_returns_invalid_state(api):
    """PRD §2.10: "then the general state check that the target resource is in a
    state permitting the requested transition (else `ERR_INVALID_STATE`)."
    PRD §3.2: "Maturation requires the lien notice to still be `SENT` and the
    logical clock now to be strictly after the `cure_deadline`; maturing at or
    before the cure deadline is rejected with `ERR_MATURE_TOO_EARLY`."

    Design: Corner/state_machines/mature_already_cured_notice_returns_invalid_state
    """
    facility = create_facility(api)
    tenant = create_tenant(api, facility["id"])
    unit = create_unit(api, facility["id"], tenant["id"])
    notice = create_lien_notice(api, unit["id"], facility["id"])
    validate_success(api.cure_unit(unit["id"], make_tenant_headers(tenant["id"])))
    resp = api.mature_lien_notice(notice["id"], make_facility_operator_headers(facility["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cure_after_maturation_returns_invalid_state(api):
    """PRD §3.2: "Curing is allowed only while the unit is `LIEN_NOTICED` and the
    unit has a `SENT` lien notice whose `cure_deadline` has not passed — that is,
    the logical clock now is at or before the `cure_deadline`; an attempt after
    that instant is rejected with `ERR_CURE_WINDOW_CLOSED`."

    Design: Corner/state_machines/cure_after_mature_returns_invalid_state
    """
    ctx = setup_matured_unit(api)  # unit is LIEN_MATURED, not LIEN_NOTICED
    resp = api.cure_unit(ctx["unit_id"], make_tenant_headers(ctx["ten"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_mature_before_cure_deadline_returns_too_early(api):
    """PRD §3.2: "Maturation requires the lien notice to still be `SENT` and the
    logical clock now to be strictly after the `cure_deadline`; maturing at or
    before the cure deadline is rejected with `ERR_MATURE_TOO_EARLY`."

    Design: Corner/validations/mature_before_deadline_returns_too_early
    """
    facility = create_facility(api)
    tenant = create_tenant(api, facility["id"])
    unit = create_unit(api, facility["id"], tenant["id"])
    notice = create_lien_notice(api, unit["id"], facility["id"])  # cure_deadline 2026-03-15
    set_clock(api, "2026-03-10T00:00:00Z")
    resp = api.mature_lien_notice(notice["id"], make_facility_operator_headers(facility["id"]))
    validate_error(resp, ApiErrorId.ERR_MATURE_TOO_EARLY.value)


def test_cure_after_deadline_returns_window_closed(api):
    """PRD §3.2: "Curing is allowed only while the unit is `LIEN_NOTICED` and the
    unit has a `SENT` lien notice whose `cure_deadline` has not passed — that is,
    the logical clock now is at or before the `cure_deadline`; an attempt after
    that instant is rejected with `ERR_CURE_WINDOW_CLOSED`."

    Design: Corner/validations/cure_after_deadline_returns_window_closed
    """
    facility = create_facility(api)
    tenant = create_tenant(api, facility["id"])
    unit = create_unit(api, facility["id"], tenant["id"])
    create_lien_notice(api, unit["id"], facility["id"])  # cure_deadline 2026-03-15
    set_clock(api, "2026-03-16T00:00:00Z")
    resp = api.cure_unit(unit["id"], make_tenant_headers(tenant["id"]))
    validate_error(resp, ApiErrorId.ERR_CURE_WINDOW_CLOSED.value)
