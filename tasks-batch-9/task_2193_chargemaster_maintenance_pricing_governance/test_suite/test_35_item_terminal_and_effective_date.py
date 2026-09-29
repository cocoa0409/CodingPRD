"""The terminal ARCHIVED state and the not-yet-effective activation precondition."""
from test_helpers import (
    api_client, validate_error, ApiErrorId,
    setup_base, create_archived_item, create_approved_item, item_lifecycle,
    read_item, read_facility, set_clock,
    ANALYST, APPROVER,
)

ITEM = dict(
    cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
    code_type="CPT", code_value="93458", cost_basis_cents=100000,
    medicare_rate_cents=50000, market_p75_cents=900000,
)


def _setup():
    set_clock("2026-09-01T00:00:00Z")
    return setup_base(
        facility_overrides={
            "name": "Mercy General", "cms_certification_number": "CCN-2193-MERCY",
            "rounding_mode": "NEAREST_CENT",
        },
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={
            "name": "Cardiac Cath Lab", "cost_center_code": "CC-4100",
            "allowed_revenue_code_values": [],
        },
    )


def test_an_archived_item_refuses_both_reactivation_and_repricing():
    """PRD §3.3: "An action that is not declared out of the item's current `lifecycle_status` —
    archiving directly from `ACTIVE`, approving from `DRAFT`, and so on — is
    `ERR_INVALID_ITEM_LIFECYCLE_STATE` (409). `ARCHIVED` is the only terminal lifecycle state."
    PRD §3.4: "Beyond the facility not being `FROZEN`, two preconditions apply: the item's
    `lifecycle_status` must not be `ARCHIVED`, otherwise `ERR_INVALID_ITEM_LIFECYCLE_STATE` (409);
    and the rule selector of §3.2 must find at least one candidate, otherwise
    `ERR_NO_APPLICABLE_PRICE_RULE` (422)."
    PRD §2.11: "Items in `DRAFT`, `PENDING_REVIEW`, `APPROVED`, `INACTIVE` or `ARCHIVED` never
    contribute to any facility aggregate."

    Design: Corner/state_machines/archived_item_terminal_state_rejects_reactivate_and_reprice
    """
    base = _setup()
    archived = create_archived_item(base, effective_from="2026-09-01T00:00:00Z", **ITEM)
    assert archived["lifecycle_status"] == "ARCHIVED"
    frozen_version = archived["version"]

    validate_error(
        api_client.charge_item_lifecycle(archived["id"], {"action": "REACTIVATE"}, APPROVER),
        ApiErrorId.ERR_INVALID_ITEM_LIFECYCLE_STATE.value,
        409,
    )
    validate_error(
        api_client.reprice_charge_item(archived["id"], ANALYST),
        ApiErrorId.ERR_INVALID_ITEM_LIFECYCLE_STATE.value,
        409,
    )

    item = read_item(archived["id"])
    assert item["lifecycle_status"] == "ARCHIVED", "no exit from the terminal state"
    assert item["version"] == frozen_version, "two refusals, zero writes"

    facility = read_facility(base["facility"]["id"])
    assert facility["active_item_count"] == 0
    assert facility["aggregate_gross_charge_cents"] == 0


def test_activation_waits_for_the_effective_instant_to_arrive():
    """PRD §3.3: "The item's `effective_from` must be at or before the logical now, otherwise
    `ERR_ITEM_NOT_YET_EFFECTIVE` (409)."
    PRD §3.3: "On success `lifecycle_status` becomes `ACTIVE`; the facility's `active_item_count`
    increases by 1, its `aggregate_gross_charge_cents` increases by the item's
    `gross_charge_cents`, its `aggregate_cost_basis_cents` increases by the item's
    `cost_basis_cents`, `aggregate_markup_ratio_bp` is recomputed, `transparency_status` is set to
    `NEEDS_REFRESH`, `chargemaster_posture` is re-derived, and `Facility.version` advances by 1."
    PRD §2.5: "Time in this system is a logical clock, never wall-clock time." A `SystemAdmin` may
    move the clock by supplying a `to_iso8601` instant to the clock-control endpoint, and every
    subsequent request evaluates "now" against the new value.

    Design: Corner/state_machines/item_activate_before_effective_from_precondition_rejected
    """
    base = _setup()
    approved = create_approved_item(base, effective_from="2026-10-01T00:00:00Z", **ITEM)
    assert approved["lifecycle_status"] == "APPROVED"
    assert approved["gross_charge_cents"] == 240000

    validate_error(
        api_client.charge_item_lifecycle(approved["id"], {"action": "ACTIVATE"}, APPROVER),
        ApiErrorId.ERR_ITEM_NOT_YET_EFFECTIVE.value,
        409,
    )
    still_approved = read_item(approved["id"])
    assert still_approved["lifecycle_status"] == "APPROVED"
    assert read_facility(base["facility"]["id"])["active_item_count"] == 0

    set_clock("2026-10-01T00:00:00Z")
    activated = item_lifecycle(approved["id"], "ACTIVATE", APPROVER)
    assert activated["lifecycle_status"] == "ACTIVE", (
        "the identical call succeeds once the logical clock reaches effective_from"
    )

    facility = read_facility(base["facility"]["id"])
    assert facility["active_item_count"] == 1
    assert facility["aggregate_gross_charge_cents"] == 240000
    assert facility["aggregate_cost_basis_cents"] == 100000
