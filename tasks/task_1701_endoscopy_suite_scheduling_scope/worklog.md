# Worklog — task_1701_endoscopy_suite_scheduling_scope

Scenario: Endoscopy Suite Scheduling & Scope Reprocessing (GI endoscopy unit): procedure booking by type & duration with prep instructions, bowel-prep adequacy & rescheduling, room/anesthesia coordination, scope inventory, reprocessing cycle & drying/storage limits, high-level disinfection documentation & scope tracking to patient, positive culture & scope quarantine, pathology specimen handoff, quality metrics (adenoma detection/withdrawal time)

Difficulty target: HARDER THAN EXPERT LEVEL.

## Step 1: Create Task Directory — 2026-08-14T09:09:00.000Z

Directory `tasks/task_1701_endoscopy_suite_scheduling_scope/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task directory touched.

## Step 3: Copy Shared Files — 2026-08-14T09:10:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1701_endoscopy_suite_scheduling_scope/workspace/INSTRUCTION.md` (1424 bytes). Executed concurrently with Step 2 scaffold generation since the copy has no dependency on scaffold output.

## Step 2: Generate Scaffold — 2026-08-14T10:55:00.000Z

Scaffold generation complete. All three artifacts are written and pass `scaffold_lint.py` with a clean verdict.

## Output files

- `/home/ubuntu/github/CodingPRD/tasks/task_1701_endoscopy_suite_scheduling_scope/SCAFFOLD.yaml` (1855 lines) — §1.0–§1.7 only
- `/home/ubuntu/github/CodingPRD/tasks/task_1701_endoscopy_suite_scheduling_scope/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1050 lines) — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1701_endoscopy_suite_scheduling_scope/SCAFFOLD_CORNER_DESIGN.yaml` (2084 lines) — single top key `scaffold_corner_design`

## Scaffold shape

- **Profile**: primary archetype `temporal_windowing`, secondary `compliance_audit`; layers = optimistic_concurrency, cascading_side_effects, rate_threshold_triggers, selector_policy; flat topology (peer entities + FKs, incl. self-referential `ProcedureBooking.rescheduled_from_id`); `segregation_of_duties` role model; immediate consistency.
- **Surface**: 14 entities, 69 endpoints (incl. `POST /endoscopy/_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default and monotonicity guard), 70 error codes, 13 calculation rules, 11 validation priority tiers, 8 roles, 3 OCC concurrency rules (booking PATCH, reschedule, quarantine release), 11 state machines (parallel booking×prep axes; cyclic Scope with quarantine branch; HLD step machine with QA-fail branch; specimen chain-of-custody).

## Difficulty depth (§1.8: 22 instances, all nine rules)

- **dual_variant_calc**: scheduled (40 min) vs actual (47 min) occupancy on the same booking; ADR STRICT 1/3=33.3 vs EXPANDED 3/6=50.0 on identical data (7-procedure fixture with prep/indication/cecal/specimen exclusions).
- **combinatorial_formula**: mode (a) 4-input window formula (base + anesthesia + exact-65th-birthday age add-on + room-class turnover → 55 min / two block ends); mode (b) pinned round-per-room-then-average utilization (41.7/24.0 → **32.9**, vs 32.8 for the non-conformant sum-then-round order — fixture verified numerically).
- **non_linear_state_machine**: booking parallel axes (cancel leaves prep PREP_CONFIRMED; abort needs combined state) vs scope cyclic double-loop with quarantine branch (reculture COMPLETE does not free the scope).
- **transitive_cascade**: depth-4 culture-POSITIVE chain (result→Scope→QuarantineCase→ScopeUsage flags→booking notification_flag) with left-exclusive/right-inclusive exposure-window boundaries, and depth-3 abort→assignment-CANCELLED→minutes-released chain.
- **priority conflicts** (3 distinct category pairs): state>safety, existence>temporal, temporal>constraint.
- **boundaries** (3 distinct metrics/endpoints): 599s/600s HLD contact; ADR null on empty denominator; storage expiry rejected at exactly `dried_at+72h`.
- **cross-entity gates** (3 pairs): booking×assignment (CONFIRMED required), quarantine-case×culture (negative reculture), booking×provider (suspension).
- **overlap semantics** (3): room half-open + turnover buffer (adjacency allowed), anesthesia closed interval (touching rejected), room-day 480-minute aggregate capacity (7th block rejected despite zero pairwise overlap).
- **compensating invariants** (2 conserved quantities): scope use_count == non-VOID usage count across start/void; anesthesia scheduled_minutes ledger across create/cancel/reschedule-cascade (85→35→0→50).

## Corner breadth (§1.9: 98 active instances + 11 excluded_because stubs)

All nine taxonomy sections: entities (11), state_machines (27), calculations (16), validations (21), endpoints (3), errors (14 — including a full 404 sweep and the two errors only reachable deep in the flow, ERR_BOOKING_NOT_IN_PROGRESS and ERR_NO_OPEN_QUARANTINE), rbac (8 — entity-backed ownership denials plus the SoD release block where the releaser equals the reculture technician), cross_cutting_layers (3 OCC stale-version instances + 3 stubs), consistency_model (1). Stubs cite §1.8 instances and all resolve.

## Verification

- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (69 endpoints, 14 entities, 22 + 98 instances, 1468 calls scanned)
- Additional scripted audits passed: placeholder closure and list-capture indexing, clock monotonicity per instance (only intentional regression test flagged), error-catalog ↔ design cross-reference complete in both directions, grounds resolution, name uniqueness across both files, OCC endpoints conform to §1.2.1 hard constraints, no forbidden concurrency vocabulary, calculation↔side-effect bidirectional match.
- All formula-derived asserts are precomputed literals verified in Python (33.3/50.0/83.3/71.4, 32.9 vs 32.8, 87.5, 11.5 vs 22.9, 480.0, 55/50 window math, 420+70>480 capacity).

One design note: `QualityMetricReport` is deliberately `common_fields: false` (immutable snapshot) so the ADR/withdrawal aggregation difficulty lives in the calculations rather than update semantics; the snapshot-stability corner instance verifies values don't drift after later procedures complete.

## Step 4: Generate PRD — 2026-08-14T11:15:00.000Z

PRD generation complete. Output written to `/home/ubuntu/github/CodingPRD/tasks/task_1701_endoscopy_suite_scheduling_scope/workspace/PRD.md` (405 lines).

**Document structure** (designed domain-specifically, not from the example's template):
- §1 Introduction — 2 paragraphs, pain-point angle (appointment book / anesthesia roster / reprocessing bench coupling)
- §2 Global Specifications — 8 subsections: RBAC (2.1, with per-role identity translations for all 8 roles), verbatim API Response Structure (2.2, byte-identical to source), Pagination (2.3), The Logical Clock (2.4), Common Resource Properties incl. the QualityMetricReport `id`/`created_at`-only exception (2.5), Reference Resolution and the 11-rung Validation Ladder (2.6, all 70 error IDs placed on rungs), Optimistic Concurrency Control (2.7, all three OCC rules with exact fields/errors), Units/Precision/Rounding (2.8)
- §3 Business Logic — 9 subsections (unit registry → booking creation → anesthesia coordination → day-of-procedure → assessment/completion/termination → reprocessing → culture/quarantine/exposure → specimen custody → quality/utilization), with all state transitions named as state pairs, all 12 calculation formulas in precise reconstructible prose, all constants embedded, and cross-entity cascades (positive-culture exposure cascade, anesthesia ledger release, scope-use compensating pair) fully enumerated
- §4 Endpoint table — 69 rows, 4 columns only
- §5 Error catalogue — 70 rows, 2 columns only

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 102 required, 102 present, 0 missing
- endpoints[].request_body: 61 required, 61 present, 0 missing
- endpoints[].query_params: 21 required, 21 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 rungs checked, 11 expressed in prose (§2.6 ladder, earliest-rung-wins), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write endpoint + expected_<parent>_version + error_id + HTTP 412 all named), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed (from/to, preconditions with error IDs, side effects incl. all cascades), 0 missing
- calculations[]: 12 checked, 12 fully expressed (constants, thresholds, boundary inclusivity, pinned rounding order), 0 missing
- validations[] conditions: 11 checked, 11 matchable to error IDs in prose, 0 missing
- endpoints[].side_effects / applies_to: 69 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: 102 checked, defaults/initial values/computed semantics reconstructible (5 precision fixes applied for booking outcome-field nulls, usage/assignment/cycle birth states, no-show from-state), 0 missing
- sibling-branch symmetry: 8 groups checked (STRICT/EXPANDED, prep adequate/inadequate, retired-vs-active positive culture, quarantined-vs-clean cycle completion, explicit-vs-selector scope, cancel from two states, reject from two states, scheduled-vs-actual duration), all equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 646
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: all 70 error IDs and all 63 enum/state literals appear in prose; no fuzzy/approximating words; no unbackticked operator syntax; §2.2 block byte-identical to `section-2.2-response-structure.md`; document ends at §5 with no audit footer. The withheld difficulty/corner design files were never opened.

## Step 6: Generate Implementation — 2026-08-14T12:07:00.000Z

All 119 checks pass on a fresh `bash start.sh` boot. The implementation is complete.

## Summary

Generated a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1701_endoscopy_suite_scheduling_scope/workspace/implementation/`:

**Files**: `start.sh` (executable, guarded `pip install`, `exec python3 app.py`, `0.0.0.0:$PORT` default 10000), `requirements.txt` (flask), `app.py`, `db.py`, `errors.py` (all 70 catalog error IDs with exact HTTP statuses), `response.py` (exact envelope: `meta`/`response_type`/`data`, pagination fields in meta), `middleware.py` (X-User-ID/X-User-Role, 8 roles), `util.py` (logical clock defaulting to `2026-08-01T00:00:00Z` with strict-regression guard, 3-fractional-digit UTC rendering, half-up Decimal rounding), `validate.py`, 15 route modules, 3 service modules.

**Coverage verified** (via 4 replay suites run against fresh boots, ~190 assertions total, all passing):
- All 69 endpoints from the scaffold endpoint table, with RBAC per endpoint and entity-backed ownership (Endoscopist/AnesthesiaProvider) checks at the correct ladder rungs
- 11-rung validation ladder ordering (verified the priority-pair difficulty cases: existence>temporal, temporal>constraint, state>safety, ownership>state, OCC after existence/before state)
- All state machines: parallel booking/prep axes, cyclic Scope with quarantine branch, ordered reprocessing steps with dwell-time gates and the HLD<300ppm fail-with-teeth path, specimen custody chain with 15/120-minute inclusive windows, assignment lifecycle with ledger cascades
- All calculations with exact constants: window math (base+anesthesia+age≥65, verified exact-65th-birthday boundary), half-open room overlap + turnover buffer + 480-min day capacity, closed-interval anesthesia overlap (touching conflicts), BBPS thresholds, 60-min strict extended-soak boundary, 599s/600s HLD contact, 72h storage expiry (expired at exact instant), deterministic scope selector (use_count → storage_expires NULLS LAST → created_at), exposure window (left-exclusive/right-inclusive, latest-negative tie-break), quality reports (STRICT 33.3 / EXPANDED 50.0 / withdrawal 480.0 / CIR 83.3 / prep 71.4 on the 7-booking fixture), pinned per-room-then-average utilization rounding (32.9, not 32.8), immutable report snapshots (no `version`/`updated_at`)

**Notable decisions**:
- Timestamps: all domain and system timestamps read the logical clock; a `_seq` insertion counter (stripped from output) breaks `created_at` ties deterministically for the selector and culture-window tie-breaks.
- `awaiting_reprocess_since` is cleared when a cycle reaches COMPLETE — required so reculture cycles on quarantined scopes compute `requires_extended_soak=false` and the §1.8 quarantine-loop fixtures (6-minute reculture clean steps) can pass; all letter-based corner cases still pass.
- Ledgers (`Scope.use_count`, `AnesthesiaProvider.scheduled_minutes`) are computed live from junction records, so the compensating-pair invariants hold by construction.
- One design-file typo noted: the anesthesia-ledger difficulty instance's intermediate assert says `scheduled_minutes == 35` after cancelling the 35-minute EGD assignment from a total of 85 (correct value 50; the fixture's later 0 and 50 checkpoints confirm). The implementation follows the pinned invariant (`sum of minutes over ASSIGNED/CONFIRMED`).

## Step 5: Generate Unit Tests — 2026-08-14T12:08:00.000Z

All checks pass. Generation complete. Here is the summary.

## What was generated

**`test_helpers/`** (9 files) under `/home/ubuntu/github/CodingPRD/tasks/task_1701_endoscopy_suite_scheduling_scope/`:
- `types.py` — 18 enums + 14 entity TypedDicts; `QualityMetricReport` correctly omits `updated_at`/`version` (PRD §2.5 immutable snapshot).
- `api_client.py` — `ApiClient(GenericApiClient)` with ~60 methods, one per PRD §4 endpoint (clock, patients, providers, procedure-types, rooms, anesthesia-providers, scopes, bookings + 10 booking actions, assignments, scope-usages, reprocessing-cycles, culture-tests, quarantine-cases + exposures, specimens + 5 custody actions, quality-reports, room-utilization).
- `api_errors.py` — all 63 PRD §5 error ids with HTTP map registered via `set_error_http_status_map`.
- `factories.py`, `constants.py` (all PRD thresholds: BBPS 6/2, 600s HLD, 300 ppm, 5/20-min clean, 72h hang time, 480-min capacity, 15/25 turnover, 65yo/45yo ages, 15/120-min specimen windows), `assertions.py` (per-entity + `assert_instants_equal` instant-comparison + `assert_rate`), `test_users.py` (8 roles; per-instance builders for entity-backed `Endoscopist`/`AnesthesiaProvider`; `NO_AUTH_HEADERS`).
- `fixtures.py` — composite chains: `run_complete_cycle`, `create_reprocessed_scope`, `create_quarantined_scope`, `create_release_ready_scope`, `setup_quality_metrics_scenario` (7-booking ADR fixture), `setup_exposure_scenario` (4-usage cascade), `setup_two_negative_cultures_scenario`, `setup_two_assignment_ledger`, `setup_utilization_scenario`, `setup_capacity_room_scenario`, plus a logical-clock tracker with per-test reset (server restarts per test; equal-time sets are no-ops so interleaved recipes never trigger `ERR_CLOCK_REGRESSION` in setup).
- `__init__.py` — barrel export.

**`test_suite/`** — `conftest.py` (session `api`, role fixtures, autouse clock-tracker reset) + 10 test files, **142 tests** (all collected by pytest, all modules import against the real framework):

- **Queue A (difficulty): 45 tests, 22/22 instances at ≥2 tests each** (the STRICT/EXPANDED instance gets 3), each tagged `Design: Difficulty/<rule_id>/<instance.name>`.
- **Queue B (corner): 97 tests, 97/98 non-stub instances**, each tagged `Design: Corner/<section>/<instance.name>`. All 11 `excluded_because:` stubs left untranslated; their difficulty-instance pointers verified to resolve.

## Key decisions and findings

- **One deliberate skip (PRD-first filter):** `Corner/validations/assignment_on_cancelled_booking_rejected`. The PRD never binds `ERR_BOOKING_NOT_SCHEDULED` to assignment creation — §3.3 names only `ERR_ANESTHESIA_TYPE_NONE`, `ERR_ANESTHESIA_PROVIDER_SUSPENDED`, and the closed-interval conflict as creation refusals — so the asserted outcome is not PRD-covered and two faithful readers could diverge. Gap left as a gap, no placeholder.
- **Citation verification was automated:** all 211 quoted docstring passages match PRD.md verbatim (whitespace-normalized), including the full validation-ladder rung sentences used by the six priority-ordering tests. 33 initial citations were rewritten to eliminate ellipses / dropped `**bold**` markers / fused non-adjacent sentences.
- **Timestamp assertions compare instants** (parse + compare) rather than strings, because PRD §2.8 mandates three fractional digits — this keeps e.g. `storage_expires_at == dried_at + 72h` assertions robust.
- **Reculture-cycle step cadence uses a 21-minute manual-clean gap**: for a `QUARANTINED` scope the 60-minute preclean-deadline reading is ambiguous in the PRD, and 21 minutes satisfies both the normal (≥5) and extended-soak (≥20) minimums, keeping quarantine-chain fixtures valid under either faithful reading.
- **Priority-pair difficulty instances** each ship a second "control" test (same tag) proving the pre-empted rung was live; the temporal control uses `validate_error_is_one_of` where both candidate errors share rung 9 (within-rung order is not PRD-pinned).
- Per-room utilization row keys (`room_id`/`occupied_minutes`/`utilization_pct`) follow the design indices' pre-audited literal assertions; top-level keys are PRD-pinned verbatim.

## Step 7: Test-Iterate to Green — 2026-08-14T12:30:00.000Z

Two 8-round parallel stability sweeps (`prd-bench-local-run --isolation per-test-server`, 142 tests/round).

**Sweep 1**: 137/142 in every round — 5 deterministic failures, no flakiness. Diagnoses and fixes:

1. `test_08_specimens.py::test_specimen_transport_120_minute_boundary` — got `ERR_INVALID_REQUEST` instead of `ERR_TRANSPORT_WINDOW_EXCEEDED`. Root cause: `implementation/routes/specimens.py` used `ERR_TRANSPORT_WINDOW_EXCEEDED` without importing it; the `NameError` fell into the generic exception handler (400). Implementation fix: added the missing import. PRD §3.8 names the error verbatim ("a later receipt is refused with `ERR_TRANSPORT_WINDOW_EXCEEDED`").
2. `test_05_anesthesia_coordination.py::test_assigned_is_not_enough_confirmed_unblocks` — setup rejected with `ERR_BOOKING_NOT_SCHEDULED` when creating an assignment on a CHECKED_IN booking. PRD §3.3 names only `ERR_ANESTHESIA_TYPE_NONE`, `ERR_ANESTHESIA_PROVIDER_SUSPENDED`, and the closed-interval conflict as assignment-creation refusals; the booking-axis SCHEDULED gate was an un-PRD-traceable over-implementation (matches the deliberately skipped corner instance `assignment_on_cancelled_booking_rejected`). Implementation fix: removed the gate and its unused import from `implementation/routes/assignments.py`.
3. `test_05_anesthesia_coordination.py::test_booking_cancel_cascade_releases_minutes` and `::test_reschedule_cascade_and_reassignment_snapshot` — both asserted `scheduled_minutes == 35` after cancelling the 35-minute EGD assignment from a ledger of 85. The pinned invariant (PRD §3.3: "sum of `minutes` over that provider's assignments in `ASSIGNED` or `CONFIRMED` status") uniquely gives 85 − 35 = 50; the "35" was the known §1.8 design-file typo propagated into the tests (the fixture's later 0/50 checkpoints corroborate 50). Test fix: corrected both assertions to 50 with an arithmetic comment.
4. `test_04_assessment_and_endings.py::test_bbps_boundary_cluster` — setup created three same-`scheduled_start` bookings in a loop that advanced the clock to that start inside the first iteration, so iterations 2–3 hit `ERR_SCHEDULED_START_IN_PAST` (PRD §3.2: "strictly in the future"). Test fix: create and prep-confirm all three bookings before advancing the clock, then drive each to IN_PROGRESS.

**Sweep 2**: 142/142 in all 8 rounds — exit condition met. No tests deleted; no assertions weakened; no `skip`/`xfail` added.

## Step 8: Finalize PRD — 2026-08-14T12:40:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1701_endoscopy_suite_scheduling_scope/workspace/PRD_FINALIZED.md` is written with exactly one inline revision.

## Line counts
- PRD.md: 404 lines; PRD_FINALIZED.md: 404 lines; delta 0 lines (single in-place sentence append, +0.0% line count, one line's content extended).

## Changes (one bullet per change)
- **§3.3 (Coordinating Anesthesia Coverage)** — revise — appended a pinning sentence to the assignment-creation paragraph: "Apart from reference resolution and payload validation, these two refusals and the overlap rule below are the only creation gates — neither the booking's booking axis nor its prep axis is consulted at creation, so an assignment may be opened against a booking in any state." — `implementation/routes/assignments.py:26-68` (Step 7 removed the un-PRD-traceable `SCHEDULED`-only gate; the PRD now explicitly forecloses re-adding any booking-state gate).

## Step 7 items that required no PRD edit
- `implementation/routes/specimens.py` import fix — pure impl bug (a `NameError` misreported as `ERR_INVALID_REQUEST`); PRD §3.8 already names `ERR_TRANSPORT_WINDOW_EXCEEDED` verbatim with the inclusive 120-minute rule, and impl now matches (specimens.py:131-134). PRD prose kept verbatim.
- `test_05` 35→50 corrections — pure test bug (a design-file typo); PRD §3.3's pinned ledger invariant ("sum of `minutes` over `ASSIGNED`/`CONFIRMED` assignments") already uniquely determines 85 − 35 = 50, matching `services/core.py:55-62`. PRD prose kept verbatim.
- `test_04` setup restructure — pure test bug (clock advanced before later bookings were created); PRD §3.2's "strictly in the future" rule already uniquely determines `ERR_SCHEDULED_START_IN_PAST`, matching `services/booking_svc.py:47-56`. PRD prose kept verbatim.

## Per-edit pre-edit search log (NO-NEW-MISMATCH RULE)
**Edit 1 (§3.3 creation-gate sentence)**
- (a) Subject: whether AnesthesiaAssignment creation consults the booking's booking-axis or prep-axis state.
- (b) Impl paths enumerated and read: `routes/assignments.py:26-68` (`create_assignment` — checks only reference resolution, provider `ACTIVE`, `anesthesia_type != NONE`, closed-interval overlap on `scheduled_start`/`scheduled_end`; never reads `booking["status"]` or `booking["prep_status"]`); `routes/assignments.py:85-119` (confirm/cancel — assignment-state gates only); `services/booking_svc.py:86-101` (`cancel_active_assignments`, `complete_confirmed_assignments` — act on `ASSIGNED`/`CONFIRMED` regardless of how late the assignment was created); all cascade callsites `routes/bookings.py:220, 417, 444, 462, 481, 519`; consumption-side gate `routes/bookings.py:293-300` (start requires a `CONFIRMED` assignment — unaffected by creation wording); ledger `services/core.py:55-62`; full-repo grep for `anesthesia_assignments` confirmed no other touchpoints.
- (c) Wording adjustment: initial draft said "the booking's own axis is not consulted"; widened to "neither the booking's booking axis nor its prep axis" after verifying `create_assignment` reads neither field, and scoped the exhaustiveness claim with "Apart from reference resolution and payload validation" so it cannot be misread as overriding ladder rungs 1-4. All enumerated paths are consistent with the final sentence.

## Step 9: Complete PRD — 2026-08-14T13:00:00.000Z

All edits are in place and the doubly-edited paragraphs read coherently. Task complete.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1701_endoscopy_suite_scheduling_scope/workspace/PRD_COMPLETED.md`

**Source vs. output:** `PRD_FINALIZED.md` (404 lines / 60,977 chars) → `PRD_COMPLETED.md` (404 lines / 64,955 chars). Char delta **+3,935**, line delta **0** (all changes inline; no sections added). 29 edits across 27 lines.

**Counts:** 24 ambiguity-pins, 5 mismatch-revisions.

**Changes (one per bullet):**

- §2.1 — revise — ambiguity — whitespace-only `X-User-ID`/`X-User-Role` headers count as empty — middleware.py:33-39
- §2.3 — insert — ambiguity — pagination: non-integer/out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST`; empty value = omitted; `created_at` ties fall to write order; filters exact-match with empty-page (not error) on no match; `has_more` = `offset + returned < total_count` — routes/helpers.py:12-50, response.py:28, services/core.py:30-31
- §2.4 — insert — ambiguity — all entity timestamps are logical-clock readings; only envelope `api_request_timestamp` uses the wall clock — util.py:24-27, services/core.py:13-14
- §2.5 — insert — ambiguity — a no-field-change write still refreshes `updated_at` and increments `version` — routes/providers.py:53, rooms.py:54, bookings.py:223
- §2.6 — insert — ambiguity — multi-reference bodies resolve in the order §3 narratives name them; absent/malformed/JSON-null body treated as `{}`; non-object body → `ERR_INVALID_REQUEST`; unknown fields ignored; required strings must be non-blank — validate.py:7-21, 133-144
- §2.6 rung 8 — insert — ambiguity — `ERR_RECULTURE_NOT_NEGATIVE` added to the ladder (was absent from all rungs) — routes/scopes.py:117-125
- §2.7 — revise — **mismatch** — version fields on non-OCC endpoints are ignored, not rejected ("do not accept" → "do not consult") — validate.py (no rejection path)
- §3.1 rooms — insert — ambiguity — `supports_anesthesia` is informational only; no validation consults it — routes/rooms.py:23-27 (sole occurrence)
- §3.1 anesthesia providers — revise — ambiguity — `scheduled_minutes` carried on every response, list entries included (not just single read) — services/core.py:128-131
- §3.2 — insert — ambiguity — `date` filter matches `scheduled_start`'s UTC day; malformed non-empty `date` → `ERR_INVALID_REQUEST` — routes/bookings.py:164-169
- §3.3 — insert — ambiguity — assignment creation gate order: suspension → `anesthesia_type`-NONE → overlap scan — routes/assignments.py:37-58
- §3.3 — insert — ambiguity — cascade-cancelled assignments keep `cancel_reason` null — services/booking_svc.py:86-94
- §3.4 — insert — ambiguity — scope auto-select ties beyond `created_at` fall to registration order — routes/bookings.py:346-353
- §3.4 — insert — ambiguity — full start-gate evaluation order pinned (ownership → booking state → explicit-scope availability → suspension → room in service → anesthesia confirmation → storage currency → pool emptiness → type match), placing room-in-service among the compliance gates at start — routes/bookings.py:276-313
- §3.5 complete — revise — **mismatch** — scope moves to `AWAITING_REPROCESS` only if still `IN_USE`; a scope quarantined mid-procedure stays `QUARANTINED` and is not re-stamped — services/booking_svc.py:104-114
- §3.5 abort — revise — ambiguity — abort `reason` is required; `actual_duration_minutes` computed with completion's truncating rule; scope cascade conditioned on `IN_USE` — routes/bookings.py:427, 439-444
- §3.5 reschedule — insert — ambiguity — old booking excluded from overlap/capacity candidates; new booking inherits patient, provider, procedure type, indication, anesthesia type, notes — routes/bookings.py:516-526
- §3.5 void — revise — ambiguity — void `reason` required; `exposure_flagged` filter accepts case-insensitive true/false, else `ERR_INVALID_REQUEST` — routes/usages.py:20-28, 52
- §3.6 — insert — ambiguity — null `awaiting_reprocess_since` ⇒ no extended soak — routes/reprocessing.py:59-63
- §3.6 — insert — ambiguity — a cycle opened while the case is already `RECULTURING` still sets `is_reculture` but leaves case status/`reculture_cycle_id` unchanged — routes/reprocessing.py:83-88
- §3.6 — insert — ambiguity — `to_step` must be a cycle status value; anything else fails schema validation with `ERR_INVALID_REQUEST` — routes/reprocessing.py:36-39, 112
- §3.6 completion — revise — **mismatch** (+pin) — the QUARANTINED branch keys on existence of an open case (not merely current scope status), and completion clears `awaiting_reprocess_since` to null — routes/reprocessing.py:168-183
- §3.6 retire — revise — ambiguity — all open quarantine cases (plural) settle at `SCOPE_RETIRED` — routes/scopes.py:85-89
- §3.7 — insert — ambiguity — on a `NEGATIVE` result, `organism`/`cfu_count` are optional and stored as supplied — routes/cultures.py:126-127
- §3.7 cascade — revise — **mismatch** — scope quarantines from any non-`OUT_OF_SERVICE` status (including `IN_USE` and already-`QUARANTINED`, the latter opening a further case); with several open cases the most recently opened governs reculture/release — routes/cultures.py:157-173, services/core.py:72-81
- §3.7 cascade — revise — **mismatch** — retired-scope branch: case created in `SCOPE_RETIRED` with `opened_at` and `resolved_at` stamped at creation, and no exposure/notification flagging occurs in that branch — routes/cultures.py:144-156
- §3.8 — insert — ambiguity — labeling a non-`COLLECTED` specimen is refused with `ERR_SPECIMEN_TERMINAL` — routes/specimens.py:92-94
- §3.8 — revise — ambiguity — specimen reject `reason` is required — routes/specimens.py:147
- §3.9 — insert — ambiguity — room-utilization missing/malformed `date` → `ERR_INVALID_REQUEST`; `rooms` entries carry `room_id`, `occupied_minutes`, `utilization_pct`, ordered by room `created_at` ascending — routes/reports.py:66-71, services/quality.py:114-133

Everything else in the implementation (envelope shape, OCC mechanics, window/duration math, overlap/capacity rules, step dwells, exposure-window semantics, quality-metric formulas, utilization rounding order, error statuses) was already uniquely pinned by the PRD and left untouched.
