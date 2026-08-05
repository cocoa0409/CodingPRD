"""Fine escalation, chronic-nuisance recompute boundaries, and the substantiation
cascade to auto-abatement (queue A depth + queue B corner)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    resident_headers, code_officer_headers,
)
from test_helpers import fixtures as fx


# --- Fine escalation combinatorial formula (queue A) ---

def test_commercial_level1_citation_fine_amount(api):
    """PRD §3.4: "The raw fine is the base multiplied by `escalation_level`, then by the
    zoning factor, then by the chronic factor; it is rounded half up to whole cents and
    then capped so that `assessed_fine_cents` never exceeds $5,000.00 (500000 cents)."
    PRD §3.4: "A zoning factor scales the fine by zoning: 1.0 for `RESIDENTIAL`, 1.5 for
    `COMMERCIAL`, 0.75 for `INDUSTRIAL`, and 1.25 for `MIXED`."

    Design: Difficulty/combinatorial_formula/fine_escalation_tiered_nonlinear_mode_a
    """
    ctx = fx.setup_level1_citation(api, zoning="COMMERCIAL")
    enf = ctx["enforcement"]
    assert enf["tier"] == "CITATION"
    assert enf["assessed_fine_cents"] == 15000


def test_commercial_second_offense_escalation_level_is_one(api):
    """PRD §3.4: "Its `escalation_level` is computed as the number of non-dismissed
    enforcements — those whose `status` is anything other than `DISMISSED` — already on
    this parcel whose `issued_at` falls within the rolling window of the last 365 days,
    counted immediately before this new one."

    Design: Difficulty/combinatorial_formula/fine_escalation_tiered_nonlinear_mode_a
    """
    ctx = fx.setup_level1_citation(api, zoning="COMMERCIAL")
    enf = ctx["enforcement"]
    assert enf["escalation_level"] == 1
    assert enf["tier"] == "CITATION"


def test_first_offense_is_warning_with_zero_fine(api):
    """PRD §3.4: "If `escalation_level` is 0 — the parcel's first non-dismissed enforcement
    in the window — the `tier` is `WARNING` and `assessed_fine_cents` is 0".

    Design: Corner/calculations/warning_first_offense_zero_fine_correct
    """
    fx.config_policy(api, "INDUSTRIAL", day_limit=75, night_limit=65)
    prop = fx.new_property(api, "INDUSTRIAL", address="111 Main St")
    _, enf = fx.substantiate_once(api, prop["id"], "2026-06-01T12:00:00Z", 90, noise_type="MACHINERY")
    assert enf["escalation_level"] == 0
    assert enf["tier"] == "WARNING"
    assert enf["assessed_fine_cents"] == 0


# --- Chronic designation count boundary (queue A) ---

def test_two_substantiations_yield_watch_not_designated(api):
    """PRD §3.4: "a count of 3 or more yields `DESIGNATED`, a count of 2 (below 3) yields
    `WATCH`, and anything below 2 yields `NONE`."

    Design: Difficulty/boundary_precision_check/chronic_designated_count_boundary
    """
    ctx = fx.setup_watch_property(api, zoning="RESIDENTIAL")
    prop = fx.read_property(api, ctx["prop_id"])
    assert prop["substantiated_violation_count"] == 2
    assert prop["chronic_status"] == "WATCH"


def test_count_two_creates_no_abatement_order(api):
    """PRD §3.4: "**Third**, if and only if this recompute newly reaches `DESIGNATED`, an
    `AbatementOrder` is auto-created for the parcel with `trigger_source` `CHRONIC_DESIGNATION`
    and `status` `PENDING`, and the parcel's `abatement_status` moves to `UNDER_ABATEMENT`."

    Design: Difficulty/boundary_precision_check/chronic_designated_count_boundary
    """
    ctx = fx.setup_watch_property(api, zoning="RESIDENTIAL")
    prop = fx.read_property(api, ctx["prop_id"])
    assert prop["abatement_status"] == "NONE"
    orders, meta = validate_paginated(
        api.list_abatement_orders(code_officer_headers(), params={"property_id": ctx["prop_id"]}))
    assert meta["total_count"] == 0
    assert len(orders) == 0


# --- Substantiation designation cascade, depth 3 (queue A) ---

def test_third_substantiation_designates_property(api):
    """PRD §3.4: "The recompute counts the parcel's non-dismissed enforcements within the
    same 365-day rolling window and sets the count into `substantiated_violation_count`:
    a count of 3 or more yields `DESIGNATED`, a count of 2 (below 3) yields `WATCH`, and
    anything below 2 yields `NONE`."

    Design: Difficulty/transitive_cascade/substantiate_chronic_designation_cascade_depth3
    """
    ctx = fx.setup_designated_property(api, zoning="RESIDENTIAL")
    prop = fx.read_property(api, ctx["prop_id"])
    assert prop["substantiated_violation_count"] == 3
    assert prop["chronic_status"] == "DESIGNATED"


def test_designation_auto_creates_pending_abatement_order(api):
    """PRD §3.4: "**Third**, if and only if this recompute newly reaches `DESIGNATED`, an
    `AbatementOrder` is auto-created for the parcel with `trigger_source` `CHRONIC_DESIGNATION`
    and `status` `PENDING`, and the parcel's `abatement_status` moves to `UNDER_ABATEMENT`."

    Design: Difficulty/transitive_cascade/substantiate_chronic_designation_cascade_depth3
    """
    ctx = fx.setup_designated_property(api, zoning="RESIDENTIAL")
    prop = fx.read_property(api, ctx["prop_id"])
    assert prop["abatement_status"] == "UNDER_ABATEMENT"
    orders, meta = validate_paginated(
        api.list_abatement_orders(code_officer_headers(), params={"property_id": ctx["prop_id"]}))
    assert meta["total_count"] == 1
    assert orders[0]["status"] == "PENDING"
    assert orders[0]["trigger_source"] == "CHRONIC_DESIGNATION"


# --- Corner: contest gating + FK filter ---

def test_warning_cannot_be_contested(api):
    """PRD §3.6: "A `Resident` contests an enforcement, moving it `ISSUED → CONTESTED`; this
    requires the enforcement's `tier` to be `CITATION`, and contesting a `WARNING` is rejected
    with `ERR_ENFORCEMENT_NOT_CITATION`."

    Design: Corner/state_machines/contest_warning_rejected_not_citation
    """
    fx.config_policy(api, "RESIDENTIAL")
    prop = fx.new_property(api, "RESIDENTIAL", address="103 Main St")
    _, enf = fx.substantiate_once(api, prop["id"], "2026-06-01T12:00:00Z", 70, noise_type="ANIMAL")
    assert enf["tier"] == "WARNING"
    resp = api.contest_enforcement(enf["id"], resident_headers())
    validate_error(resp, ApiErrorId.ERR_ENFORCEMENT_NOT_CITATION.value)


def test_enforcements_filtered_by_property(api):
    """PRD §4: GET `/enforcements` — "List enforcements". PRD §3.4: an enforcement carries
    "the parcel's `property_id` (denormalized for escalation scoping)."

    Design: Corner/endpoints/enforcements_filter_by_property_fk
    """
    fx.config_policy(api, "RESIDENTIAL")
    prop = fx.new_property(api, "RESIDENTIAL", address="118 Main St")
    _, enf = fx.substantiate_once(api, prop["id"], "2026-06-01T12:00:00Z", 70, noise_type="ANIMAL")
    data, meta = validate_paginated(
        api.list_enforcements(code_officer_headers(), params={"property_id": prop["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == enf["id"]
    assert data[0]["property_id"] == prop["id"]
