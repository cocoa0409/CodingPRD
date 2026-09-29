# Step 7 diagnostic notes — task_2634

## Iteration 1 — sweep launched 2026-09-04T08:46Z
512 tests / 63 modules, per-test-server isolation, 8 concurrent rounds.
Smoke check: `python3 app.py` boots on PORT override, GET /api/units -> 404 (expected, no such path).

### Iteration 1 result
All 8 rounds identical: 445/512 passed, 39 failed, 28 errors, 67 distinct tests.
Perfect agreement across rounds => no load-induced noise; every failure deterministic.

### Iteration 1 failure groups and verdicts

**A. Unit projection missing readiness fields (17 tests: 07, 12, 13x2, 48x2, 49, 50x2, 55, 61x8)**
`KeyError: 'readiness_reason' / 'current_drill_id' / 'mean_d2i_minutes'` on a unit read.
PRD 3.8 covers verbatim: "it publishes `cesarean_readiness_state`, `readiness_reason`,
`current_drill_id`, `current_drill_expires_at` and `mean_d2i_minutes` on the unit."
=> STEP 3 implementation fix. views.FIELDS["units"] extended with the four missing
public keys; bp_units.create_unit seeds them; calc.rederive_unit writes them publicly
instead of into a private `_readiness_reason`.

**B. Fixtures expecting OPEN/RATIO_STRAINED on a drill-less unit (15 tests: 03, 04x6, 05, 11x6, 17x2)**
Adjudicated in the implementation's favour. PRD 3.3: "`INDUCTION_FROZEN` when ... or
`cesarean_readiness_state` is `NOT_READY`", PRD 3.1: a new unit opens "with
`cesarean_readiness_state` at `NOT_READY` because no drill has yet been validated", and
the reason code `READINESS_NOT_READY` exists for exactly that branch. Passing siblings
(test_53, test_54, test_63, test_07) already assert a drill-less unit is INDUCTION_FROZEN.
=> the five fixtures were PRD-violating. test_helpers/fixtures.py gained
`lift_unit_off_not_ready()`, which validates one drill so the unit can legally be OPEN.

**C. Drill started before it was due (16 tests: 15x7, 18x9)**
Setup died on `ERR_DRILL_NOT_DUE`. PRD 3.8: a start is permitted "once the current instant
is at or after `scheduled_for_utc`, the boundary instant counting as due". The fixtures
scheduled the drill 5 minutes into the future and started it immediately.
=> fixture fix: `scheduled_for_utc` moved to the clock instant, `decision_at` left where it
was so the measured d2i stays inside the 30-minute pass window.

**D. Bed retirement named the wrong guard (2 tests: 52)**
Impl answered `ERR_BED_NOT_RELEASABLE`; PRD 3.2 names `ERR_BED_HAS_FUTURE_HOLDS` "while any
booking in `CAPACITY_HELD` or `CONFIRMED` still points at the bed". Such a booking always
leaves its bed `HELD`, so the source-state guard would make the named error unreachable.
=> STEP 3 implementation fix: both guards merged into one band function, future-holds first.

**E. Shift cancellation named the wrong guard (1 test: 52)**
Impl answered `ERR_INVALID_STATE_TRANSITION`; PRD 3.3: cancellation "is refused with
`ERR_SHIFT_HAS_ACTIVE_COVERAGE` while any care assignment referencing the entry is still
`ACTIVE`". => STEP 3 implementation fix, same merge technique.

**F. Mobilisation invented an error id (1 test: 44)**
Impl answered `ERR_SHIFT_NOT_ACTIVE`, which PRD 3.8 never lists for mobilisation; the roster
requirement is part of "each holding an `ACTIVE` roster entry on the unit, refused otherwise
with `ERR_CESAREAN_TEAM_INCOMPLETE`". => STEP 3 implementation fix: the 8.08 roster check was
deleted and the roster predicate folded into the 11.4 team-completeness check.

**G. 14.1 vs 11.4 precedence (1 test: 50)**
The test expected `ERR_DRILL_TIMESTAMP_OUT_OF_RANGE` to outrank
`ERR_DRILL_PARTICIPANTS_INSUFFICIENT`. The ladder puts 11.4 above 14.1 and PRD 2.6 lists no
combination reversing it. => STEP 2 test fix: expectation and name flipped to the 11.4 id.

**H. `one_to_one_required` after a refused mobilisation (1 test: 58)**
The test asserted `False` on an encounter carrying a `DECISION_DECLARED` event, contradicting
"`TIER_IV` fires when ... a cesarean event on the encounter is in `DECISION_DECLARED`" plus
"sets `one_to_one_required` to true when ... the tier resolved to `TIER_IV`".
=> STEP 2 test fix: `True` + `TIER_IV` + equality against a pre-refusal capture.

**I. version 2 straight after creation (5 tests: 21x2, 32x2, 34)**
PRD 2.4: "`version` is an integer that starts at 1 when the record is created". The creation
path ran the acuity derivation and let it bump its own subject. => STEP 3 implementation fix:
`rederive_encounter(..., bump_self=False)` from `create_encounter` only.

**J. `assert <Response [400]>` (1 test: 32)**
A refused `requests.Response` is falsy, so the assertion could never hold.
=> STEP 2 test fix: assert `status_code == 400` (the sibling test already validates the id).

**K. Activation reloaded after a later successful rescission (1 test: 33)**
The fixture rescinded the activation and the test then re-read it expecting
`STAGE_1_IN_PROGRESS`. => STEP 2 test fix: capture the row between the two refusals and the
successful rescission, and assert against that capture.

**L. `highest_stage_reached` after the first gate-1 completion (1 test: 46)**
The test expected 0. PRD 3.7 gates completion on "`highest_stage_reached` must be at least the
item's `stage_gate`" with an exception granted only "while the activation is still
`ACTIVATED`", and PRD 3.7 rescission speaks of "while `highest_stage_reached` is 1 or less";
the same fixture completes a second gate-1 item afterwards, which only succeeds at 1. A
sibling test (33) asserts 1 for the same state. => STEP 2 test fix: 0 -> 1.

**M. Dict keys iterated as records (1 test: 55)**
`for member in participants:` over a dict yielded the string keys.
=> STEP 2 test fix: `.values()`.

**N. Deficit/posture after a REVIEW_PENDING delivery walk-on (1 test: 08)**
Not uniquely derivable. "`TIER_IV` fires when ... `DECISION_DECLARED`, `TEAM_MOBILIZED` or
`INCISION_RECORDED`" with "and to false otherwise" drops the deficit to 0.5 the instant the
event leaves theatre; "Closing ... drops the encounter from the in-theatre clause of the
posture derivation" keeps 4.0 alive until the event is `CLOSED`. The record-delivery paragraph
names neither. => STEP 1c split: the two assertions resting on that choice (deficit 4.0,
posture INDUCTION_FROZEN) are dropped; the figure both readings share -- a non-OPEN posture and
therefore a 75-minute buffer, plus `turnover_clear_at` at 10:15 -- is kept.

## Iteration 2 — sweep launched 2026-09-04T09:31Z, joined 09:47Z
All 8 concurrent rounds: 512/512 passed, 0 failed, 0 errors, 0 skipped, ~989 s each.
Eight distinct results.$i.json artifacts, every test status `passed` in every round.
No further iteration required.
