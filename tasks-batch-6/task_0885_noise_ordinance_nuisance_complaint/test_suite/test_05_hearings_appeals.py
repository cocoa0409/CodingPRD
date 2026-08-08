"""Appeal hearings: provisional-vs-final fine, the remand cycle, segregation of duties,
officer-buffer overlap, and decide/schedule state gating (queue A depth + queue B corner)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    resident_headers, code_officer_headers, hearing_officer_headers,
)
from test_helpers import fixtures as fx


# --- Dual-variant fine: provisional (assessed) vs final (effective) (queue A) ---

def test_reduced_hearing_sets_effective_fine_below_assessed(api):
    """PRD §3.6: "The reconciled fine becomes `assessed_fine_cents` multiplied by one minus
    `reduction_pct`, rounded half up to whole cents, and is written to `effective_fine_cents`
    (strictly less than the assessed amount whenever `reduction_pct` is above 0)."

    Design: Difficulty/dual_variant_calc/enforcement_fine_provisional_vs_final
    """
    ctx = fx.setup_scheduled_hearing(api, zoning="COMMERCIAL", clock="2026-06-01T00:00:00Z",
                                     scheduled_at="2026-06-05T10:00:00Z")
    hearing = fx.decide(api, ctx["hearing_id"], "REDUCED", deciding_user_id="hof-9", reduction_pct=0.25)
    assert hearing["outcome"] == "REDUCED"
    enf = fx.read_enforcement(api, ctx["enforcement"]["id"])
    assert enf["effective_fine_cents"] == 11250
    assert enf["status"] == "REDUCED"


def test_reduced_hearing_leaves_assessed_fine_unchanged(api):
    """PRD §3.4: "At issuance `effective_fine_cents` equals `assessed_fine_cents`."
    PRD §3.6: "The reconciled fine becomes `assessed_fine_cents` multiplied by one minus
    `reduction_pct`, rounded half up to whole cents, and is written to `effective_fine_cents`".

    Design: Difficulty/dual_variant_calc/enforcement_fine_provisional_vs_final
    """
    ctx = fx.setup_scheduled_hearing(api, zoning="COMMERCIAL", clock="2026-06-01T00:00:00Z",
                                     scheduled_at="2026-06-05T10:00:00Z")
    fx.decide(api, ctx["hearing_id"], "REDUCED", deciding_user_id="hof-9", reduction_pct=0.25)
    enf = fx.read_enforcement(api, ctx["enforcement"]["id"])
    assert enf["assessed_fine_cents"] == 15000


# --- Remand cycle (queue A) ---

def test_remand_returns_enforcement_to_contested(api):
    """PRD §3.6: "A **`REMANDED`** decision sets the hearing `PENDING → REMANDED` and returns
    the enforcement `HEARING_SCHEDULED → CONTESTED`, so a fresh hearing may be scheduled — this
    is the cyclic appeal loop."

    Design: Difficulty/non_linear_state_machine/enforcement_appeal_remand_cycle
    """
    ctx = fx.setup_scheduled_hearing(api, zoning="COMMERCIAL", scheduled_at="2026-05-20T10:00:00Z")
    fx.decide(api, ctx["hearing_id"], "REMANDED", deciding_user_id="hof-9")
    enf = fx.read_enforcement(api, ctx["enforcement"]["id"])
    assert enf["status"] == "CONTESTED"


def test_fresh_hearing_after_remand_reenters_scheduled(api):
    """PRD §3.6: "A **`REMANDED`** decision sets the hearing `PENDING → REMANDED` and returns
    the enforcement `HEARING_SCHEDULED → CONTESTED`, so a fresh hearing may be scheduled — this
    is the cyclic appeal loop."

    Design: Difficulty/non_linear_state_machine/enforcement_appeal_remand_cycle
    """
    ctx = fx.setup_scheduled_hearing(api, zoning="COMMERCIAL", scheduled_at="2026-05-20T10:00:00Z")
    fx.decide(api, ctx["hearing_id"], "REMANDED", deciding_user_id="hof-9")
    hearing2 = fx.schedule_hearing(api, ctx["enforcement"]["id"], "2026-05-25T10:00:00Z", "hof-9")
    assert hearing2["outcome"] == "PENDING"
    enf = fx.read_enforcement(api, ctx["enforcement"]["id"])
    assert enf["status"] == "HEARING_SCHEDULED"


# --- Priority-pair: SoD (9) beats reduction-range (10) (queue A) ---

def test_sod_reported_before_out_of_range_reduction(api):
    """PRD §2.5: "at hearing decision time the segregation-of-duties check (step 9) is
    evaluated before the reduction-fraction range check (step 10), so a decision submitted by
    the issuing officer with an out-of-range `reduction_pct` fails with
    `ERR_SEGREGATION_OF_DUTIES`, not `ERR_REDUCTION_PCT_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/decide_safety_beats_constraint
    """
    ctx = fx.setup_scheduled_hearing(api, zoning="COMMERCIAL", scheduled_at="2026-05-20T10:00:00Z")
    # deciding user == issuing officer "officer-1"; reduction_pct 1.5 is out of range
    resp = api.decide_hearing(ctx["hearing_id"], {"outcome": "REDUCED", "reduction_pct": 1.5},
                              hearing_officer_headers("officer-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_rejected_self_decision_leaves_hearing_pending(api):
    """PRD §3.6: "Deciding requires the hearing to be `PENDING`, else `ERR_HEARING_NOT_PENDING`."
    PRD §3.6: "a decision by the issuing officer is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/decide_safety_beats_constraint
    """
    ctx = fx.setup_scheduled_hearing(api, zoning="COMMERCIAL", scheduled_at="2026-05-20T10:00:00Z")
    api.decide_hearing(ctx["hearing_id"], {"outcome": "REDUCED", "reduction_pct": 1.5},
                       hearing_officer_headers("officer-1"))
    # A different, valid officer can still decide -> proves the hearing remained PENDING.
    hearing = fx.decide(api, ctx["hearing_id"], "UPHELD", deciding_user_id="hof-9")
    assert hearing["outcome"] == "UPHELD"


# --- Decide state gating (queue B) ---

def test_decide_already_decided_hearing_rejected(api):
    """PRD §3.6: "Deciding requires the hearing to be `PENDING`, else `ERR_HEARING_NOT_PENDING`."

    Design: Corner/state_machines/decide_already_decided_hearing_not_pending
    """
    ctx = fx.setup_scheduled_hearing(api, zoning="COMMERCIAL", scheduled_at="2026-05-20T10:00:00Z")
    fx.decide(api, ctx["hearing_id"], "UPHELD", deciding_user_id="hof-9")
    resp = api.decide_hearing(ctx["hearing_id"], {"outcome": "DISMISSED"}, hearing_officer_headers("hof-9"))
    validate_error(resp, ApiErrorId.ERR_HEARING_NOT_PENDING.value)


# --- Schedule requires CONTESTED (queue A) ---

def test_schedule_hearing_on_issued_enforcement_rejected(api):
    """PRD §3.6: "Scheduling a hearing on an enforcement that is not `CONTESTED` is rejected
    with `ERR_ENFORCEMENT_NOT_CONTESTED`."

    Design: Difficulty/cross_entity_state_dependency/schedule_hearing_requires_enforcement_contested
    """
    ctx = fx.setup_level1_citation(api, zoning="COMMERCIAL")  # enforcement is ISSUED, never contested
    resp = api.create_hearing(ctx["enforcement"]["id"],
                              {"scheduled_at": "2026-05-20T10:00:00Z", "hearing_officer_id": "hof-9"},
                              hearing_officer_headers("hof-9"))
    validate_error(resp, ApiErrorId.ERR_ENFORCEMENT_NOT_CONTESTED.value)


def test_no_hearing_created_when_enforcement_not_contested(api):
    """PRD §3.6: "A `HearingOfficer` then schedules an appeal hearing on a contested citation,
    moving it `CONTESTED → HEARING_SCHEDULED` and creating a `Hearing` in `PENDING`."

    Design: Difficulty/cross_entity_state_dependency/schedule_hearing_requires_enforcement_contested
    """
    ctx = fx.setup_level1_citation(api, zoning="COMMERCIAL")
    api.create_hearing(ctx["enforcement"]["id"],
                       {"scheduled_at": "2026-05-20T10:00:00Z", "hearing_officer_id": "hof-9"},
                       hearing_officer_headers("hof-9"))
    data, meta = validate_paginated(api.list_hearings(ctx["enforcement"]["id"], code_officer_headers()))
    assert meta["total_count"] == 0


# --- Officer-buffer overlap (queue A) ---

def _contested_citation(api, prop_id, base_day, second_day):
    d = fx.OVER_LIMIT_DB["COMMERCIAL"]
    fx.substantiate_once(api, prop_id, f"{base_day}T12:00:00Z", d, noise_type="AMPLIFIED_MUSIC")
    _, enf = fx.substantiate_once(api, prop_id, f"{second_day}T12:00:00Z", d, noise_type="AMPLIFIED_MUSIC")
    fx.contest(api, enf["id"])
    return enf


def test_hearing_within_officer_buffer_rejected(api):
    """PRD §3.6: "if any other hearing for the same `hearing_officer_id` has a slot within 60
    minutes of this one, the request is rejected with `ERR_HEARING_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/hearing_slot_officer_buffer_overlap
    """
    fx.config_policy(api, "COMMERCIAL", day_limit=65, night_limit=55)
    propA = fx.new_property(api, "COMMERCIAL", address="16 A St")
    propB = fx.new_property(api, "COMMERCIAL", address="17 B St")
    enfA = _contested_citation(api, propA["id"], "2026-05-10", "2026-05-11")
    enfB = _contested_citation(api, propB["id"], "2026-05-10", "2026-05-11")
    fx.schedule_hearing(api, enfA["id"], "2026-05-20T10:00:00Z", "hof-9", duration_minutes=30)
    resp = api.create_hearing(enfB["id"],
                              {"scheduled_at": "2026-05-20T10:45:00Z", "hearing_officer_id": "hof-9",
                               "duration_minutes": 30},
                              hearing_officer_headers("hof-9"))
    validate_error(resp, ApiErrorId.ERR_HEARING_SLOT_CONFLICT.value)


def test_hearing_outside_officer_buffer_allowed(api):
    """PRD §3.6: "if any other hearing for the same `hearing_officer_id` has a slot within 60
    minutes of this one, the request is rejected with `ERR_HEARING_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/hearing_slot_officer_buffer_overlap
    """
    fx.config_policy(api, "COMMERCIAL", day_limit=65, night_limit=55)
    propA = fx.new_property(api, "COMMERCIAL", address="16 A St")
    propB = fx.new_property(api, "COMMERCIAL", address="17 B St")
    enfA = _contested_citation(api, propA["id"], "2026-05-10", "2026-05-11")
    enfB = _contested_citation(api, propB["id"], "2026-05-10", "2026-05-11")
    fx.schedule_hearing(api, enfA["id"], "2026-05-20T10:00:00Z", "hof-9", duration_minutes=30)
    resp = api.create_hearing(enfB["id"],
                              {"scheduled_at": "2026-05-20T12:00:00Z", "hearing_officer_id": "hof-9",
                               "duration_minutes": 30},
                              hearing_officer_headers("hof-9"))
    hearing = validate_success(resp, 201)
    assert hearing["outcome"] == "PENDING"
