# Worklog — task_2634_labor_delivery_unit_staffing_perinatal_safety_bundles

## Step 1: Create task directory — 2026-09-03T22:43:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2634_labor_delivery_unit_staffing_perinatal_safety_bundles` and its `workspace/` subdirectory. Index 2634 was pre-assigned by the invoking command (no scan of ./tasks/ performed, per instruction, to avoid collision with the up-to-32 concurrent pipelines on this host).

## Step 2 (part a/b/c): Generate scaffold — SCAFFOLD.yaml — 2026-09-04T00:05:00.000Z

ORCHESTRATOR NOTE (decision, no user available to consult): the first Step-2 subagent, spawned per the skill as a single scaffold generator, was killed by the harness with
`API Error: Claude's response exceeded the 64000 output token maximum` and left ZERO files on disk. Because the difficulty instruction ("harder than expert level") pushes the scaffold well past 4000 lines, one agent cannot emit it inside the output cap even with chunked appends. I therefore partitioned Step 2 into four sequential subagents, each writing a bounded slice by append-only `cat >>` (never Write, never re-emit):
  2a → preamble + §1.0 envelope + §1.1 entities + §1.2/§1.2.1 state machines + concurrency + §1.3 calculations + §1.4 validations
  2b → §1.5 endpoints
  2c → §1.6 errors + §1.7 roles + scaffold_lint.py to clean
  2d → SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8), then §1.9 in two appending passes
This preserves the skill's context-isolation intent (each slice is a fresh context reading only what it needs) and adds durability: a death mid-slice loses at most one slice, and the file on disk is always a valid prefix.

### 2a summary (verbatim)

PART 1 of the scaffold is complete and validated.

**File**: SCAFFOLD.yaml — **1979 lines**

**Keys written (exactly the assigned set, verified by `yaml.safe_load`)**: `scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`.

**Complexity profile**
- `domain_name: perinatal-safety-ops`, `api_prefix: /obstetric-units`
- primary archetype `compliance_audit`, secondary `quota_allocation`
- layers: `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`
- topology `graph`, state-machine shape `parallel`, role model `segregation_of_duties`, consistency `immediate`

**Counts**
- 15 entities (all `common_fields: true`, 4 self-referential FKs, canonical `FK -> {Entity}.id` prefixes)
- 13 state machines / **70 transitions**, incl. LaborEncounter split into two parallel axes (`labor_phase`, `staffing_state`), cyclic induction/escalation/drill/review/bed/pass machines, fork-join bundle and cesarean machines, and two named 4–5-hop cascades (phase advance -> 1:1 flip -> re-price -> sibling breach -> posture freeze -> bookings bumped -> beds released; drill invalidate -> currency lapse -> readiness NOT_READY -> electives bumped -> beds released)
- 4 concurrency rules, all OCC-on-parent-`version` with `expected_<parent>_version` + HTTP 412 (`ERR_STALE_ENCOUNTER_VERSION`, `ERR_STALE_UNIT_VERSION` x2, `ERR_STALE_ACTIVATION_VERSION`)
- 15 calculations, including 2 dual-variant pairs (bundle timeliness activation- vs sequence-anchored; quality rates delivery- vs admission-cohort), Rule-2 modes (a)/(b)/(c), 2 conserved-quantity invariants (acuity load units, LDR bed-minutes/day), explicit inclusive/strict boundary and empty-set-fallback semantics
- 36 validation rows spanning priorities 1 -> 16; priorities unique and monotonic; **5 priority-conflict pairs** documented as inline `note:` entries.

**Naming conventions committed in the file header**
- endpoints: kebab-case plural collections + camelCase path params, e.g. `POST /labor-encounters/{encounterId}/advance-phase`; drivers `POST /_clock/set_current_utc` (server default `2026-08-01T00:00:00Z`) and `POST /obstetric-units/{unitId}/capacity-sweep`
- errors: `ERR_<SUBJECT>_<CONDITION>`; OCC losers `ERR_STALE_<PARENT>_VERSION` (412)
- roles: ChargeNurse, BedsideNurse, ObstetricianAttending, AnesthesiaLead, PerinatalSafetyOfficer, PatientAccessCoordinator

**Fixes applied this pass**: (1) renumbered the 8.x state band so all 36 priorities are unique floats; (2) removed a contradictory `ERR_ENCOUNTER_COVERAGE_INSUFFICIENT` citation from the COVERAGE_BREACH -> RATIO_COVERED edge; (3) added the missing validation row for `ERR_ENCOUNTER_BED_NOT_ASSIGNED` (priority 13.3); (4) fixed a stray CJK character in a header comment. All 116 distinct `ERR_*` ids appear in some validation row, so §1.6 can be cataloged mechanically. No sibling task directories were read.

### 2b summary (verbatim)

PART 2 complete. `endpoints:` appended (1979 -> **3444 lines**, **96 endpoints**). Parse check passes; no `errors:`/`roles:`/`scaffold_*_design` keys written.

**Counts by method:** POST 55, GET 37, PATCH 3, DELETE 1 (201: 14 creators, 200: 82). Every endpoint carries `method, path, description, roles, code, input, input_types, output, validation_priorities (ascending), transitions, side_effects, error_ids`.

**Endpoint -> state machine coverage (verified programmatically):** extracted the HTTP verb+path from all 11 machines' `trigger:` strings and matched against declared endpoints — **zero unmatched triggers**, including system edges (`DELIVERED -> REVIEW_PENDING/CLOSED`, `SUPERSEDED` on snapshot create, pass `EXPIRED` in capacity-sweep). Both drivers present: `POST /_clock/set_current_utc` (+ `GET /_clock`) and `POST /obstetric-units/{unitId}/capacity-sweep`.

**Gaps found and resolutions (each recorded inline in the YAML):**
- §1.2 declares no creation edge for `EmergencyCesareanEvent` yet §1.4 priorities 4 and 8.01 name `POST /emergency-cesareans` -> declared it as the clinician-declared entry producing the identical `DECISION_DECLARED` row.
- §1.1 says several children's `unit_id`/`encounter_id` are "set from the creation path" while §1.4 names flat collection paths -> kept flat paths, id in body, added "§1.4 GAP RESOLUTION" notes.
- No error_id for holding a non-AVAILABLE LDR bed -> reused `ERR_BED_TURNOVER_CONFLICT`.
- No error_id for drill `scheduled_for_utc >= clock_now` -> reused `ERR_DRILL_TIMESTAMP_OUT_OF_RANGE`.
- `AnesthesiaLead` had no §1.2 `actor:` -> given co-role write surface on shift-assignments, drill create/document, OR/readiness reads.
- Vocabulary audit: one invented error_id (`ERR_SUPPORT_PASS_NOT_FOUND`) rewritten to the declared `ERR_PASS_NOT_FOUND`; every declared ERR_* now reachable from some endpoint.
- YAML hazard fixed: bare `?` optional markers in flow lists break the parser — all 32 such `input:` lines now quote the optional entries.

Reverse-reachability and observability audits pass: every `FK ->` field is reachable via a sub-resource GET or filtered list, and all 14 §1.3 calculations are named by at least one endpoint with dedicated computed reads (`capacity-summary`, `coverage-report`, `readiness-report`, `.../coverage-summary`, `.../timeliness-report`, snapshot detail for both quality-rate variants).

### 2c summary (verbatim)

§1.6 and §1.7 written; scaffold lints clean.

**§1.6 Error Code Catalog — 116 ids.** Closure verified both directions by script: every id appears in some `validations[].error_id` AND in some endpoint's `error_ids:` — 0 orphans, 0 missing; each catalog `http:` equals the validation row's `http_status:` — 0 mismatches. HTTP distribution: **409 x49, 422 x41, 404 x15, 400 x6, 412 x3, 403 x2**. Emitted with `id`/`http`/`condition`, ordered along the §1.4 priority ladder with group comments. 8 first-draft conditions corrected after cross-checking against §1.1/§1.2 declarations.

**§1.7 RBAC Matrix — 6 roles, `segregation_of_duties`.** ChargeNurse (entity_backed:StaffMember, 14 exclusive / 58 shared), BedsideNurse (0/32), ObstetricianAttending (11/44), AnesthesiaLead (0/23), PerinatalSafetyOfficer (11/48), PatientAccessCoordinator (opaque, 5/20). Operation lists generated from §1.5 and asserted equal to the union of each endpoint's declared `roles:`. BedsideNurse and AnesthesiaLead legitimately hold zero single-role endpoints (verified), so `exclusive_operations: []` with an explanatory note. Six SoD pairs made explicit in a header block and per-role `segregation_of_duties:` entries, all enforced by `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (403, priority 10): SOD-1 complete checklist item x close that debrief; SOD-2 document drill x validate drill; SOD-3 hold a CareAssignment x facilitate a review on that encounter; SOD-4 facilitate/cover x close that review; SOD-5 be in `mobilized_staff_ids` x close that cesarean; SOD-6 facilitate a review in-window x certify that snapshot.

**Fixes applied (all surgical, in place)**
1. **`api_prefix: /obstetric-units` -> `""`** — root cause of a 35-violation lint wall: §1.5 mounts 14 sibling collections at `/`, so no endpoint path started with the declared prefix and the linter's collection-segment derivation returned nothing. Empty prefix (the template default) dropped 35 -> 7 violations.
2. **Added 5 flat reverse-reachability GETs** (96 -> 101 endpoints): `GET /staff-members`, `GET /bundle-checklist-items` (+`/{itemId}`), `GET /cesarean-readiness-drills`, `GET /quality-measure-snapshots`. The `performed_by_staff_id` / `documented_by_staff_id` filters double as the SOD-1/SOD-2 audit channels.
3. **PSO actor stamps re-based on StaffMember** — `validated_by_user_id`, `closed_by_user_id`, `certified_by_user_id` said "Opaque PerinatalSafetyOfficer identifier", which would make all five priority-10 SoD checks vacuous. Reworded to "StaffMember.id … copied from X-User-ID (audit stamp, deliberately not a navigable FK)"; kept off the `FK ->` prefix so lint check (f) does not demand reverse GETs for audit stamps.
4. Roles matrix regenerated after (2) so it stays byte-consistent with the 101 endpoints.

**Final lint verdict (verbatim)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    101
  §1.1 entities declared:     15
  §1.8 instances scanned:     0
  §1.9 instances scanned:     0
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Caveat: `scaffold_lint.py <task_dir>` hard-exits when the design files are absent, so 2c ran the 3-explicit-path form with empty stubs to execute the scaffold-level check (f) + coverage stats. Checks (a)-(e) scan §1.8/§1.9 call sites and must be re-run after 2d.

**SCAFFOLD.yaml final line count: 4286.**

## Step 2 (part d): SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 2026-09-04T01:45:00.000Z

§1.8 complete: **3272 lines**, 9 rule blocks x 2 instances = **18 instances**, 434 calls scanned, lint clean.

Instance names (needed by §1.9 for `excluded_because` citations):
- dual_variant_calc: `hypertension_bundle_activation_anchored_100_vs_sequence_anchored_87_50`, `september_snapshot_delivery_cohort_33_3333_vs_admission_shadow_0_0000`
- combinatorial_formula: `charge_slot_nested_min_max_with_tier_iv_focus_penalty_yields_1_0`, `posture_buffer_projection_cycle_pinned_order_freezes_645_beside_675`
- non_linear_state_machine: `encounter_staffing_axis_breaches_twice_while_phase_axis_advances_to_active_first_stage`, `induction_booking_two_laps_of_hold_confirm_bump_requeue_cycle_promotes_to_medically_indicated`
- transitive_cascade: `drill_invalidation_cascades_currency_to_readiness_to_elective_bump_to_bed_release`, `record_delivery_cascades_event_status_to_delivery_mode_to_draft_snapshot_rates_to_or_bed_turnover`
- priority_pair_validation_conflict: `divert_posture_at_8_02_outranks_exceeded_day_bed_minute_budget_at_15_on_induction_hold`, `unattached_performer_at_12_outranks_future_dated_completed_at_at_14_1_on_checklist_complete`
- boundary_precision_check: `day_bed_minute_budget_rejects_1290_against_1289_and_admits_1290_against_1290`, `drill_pass_threshold_admits_thirty_minutes_fifty_nine_seconds_and_refuses_thirty_one_minutes_flat`
- cross_entity_state_dependency: `second_stage_advance_blocked_by_unit_not_ready_then_unblocked_by_validating_a_drill_nothing_on_the_encounter_changing`, `mobilized_cesarean_event_blocks_partner_pass_check_in_while_admitting_or_credentialed_doula_pass`
- resource_temporal_overlap: `bed_hold_collides_inside_the_frozen_buffer_and_on_the_touching_endpoint_but_admits_one_minute_later`, `shift_window_admits_the_touching_sixteen_hundred_start_and_the_exact_720_minute_span_but_refuses_15_59_and_721`
- compensating_invariant: `bundle_rescind_returns_the_shared_shift_load_to_1_3_not_to_zero_and_not_to_2_8`, `bump_and_cancel_credit_back_the_hold_time_frozen_645_and_375_while_the_untouched_165_stays_committed`

**SCAFFOLD.yaml edits: none** — every chain composed from existing §1.5 endpoints; no §1.5 ladder step needed.

Key reachability findings recorded for downstream steps:
- **Bed interval rule (13.3) is only reachable through a recycled bed.** Priority 8.07 requires the target bed AVAILABLE, but any booking in {CAPACITY_HELD, CONFIRMED} pins its bed at HELD and `PATCH /beds/{bedId}` refuses HELD. Working chain: hold -> confirm -> **admit** (bed OCCUPIED, `held_booking_id := null`, booking ADMITTED which is inside 13.3's colliding set) -> `transfer-out` (bed TURNOVER) -> advance clock past `turnover_clear_at` -> `capacity-sweep` step 2 (bed AVAILABLE). New holds then hit the ADMITTED booking's frozen window. The EXPIRED-hold route does NOT work — EXPIRED is outside the colliding set.
- `turnover_buffer_minutes` = 45 under posture OPEN, 75 otherwise (exploited by compensating_invariant instance 18: P frozen 645 under OPEN, Q frozen 375 under RATIO_STRAINED, R=165 as control).
- Linter facts: `captures:` cannot read computed-view outputs (SweepResult, CapacitySummary are not §1.1 entities) — capture the equivalent entity field and state view expectations as prose asserts.

Final lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (§1.8 instances scanned: 18, calls 434.)

## Step 2 (part e/f/g): SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 2026-09-04T05:15:00.000Z

ORCHESTRATOR NOTE: §1.9 was likewise split into three append-only passes to stay under the 64k output cap — P1 `entities`/`state_machines`/`calculations`, P2 `validations`/`endpoints`, P3 `errors`/`rbac`/`cross_cutting_complexity_layers`/`consistency_model`. Each pass read the prior passes' output for style and name-uniqueness, then re-ran scaffold_lint.py over the whole task dir.

**Final: 9764 lines, 9 sections, 110 instances (81 with full `test_recipe`, 29 `excluded_because` stubs), 1586 §1.8+§1.9 calls scanned, lint clean.**

P1 (48 instances: entities 13 real + 2 stubs; state_machines 12 real + 5 stubs; calculations 9 real + 7 stubs) — no SCAFFOLD.yaml edits. Fixed 4 invalid inline flow-mapping `captures:` (a `[` terminates a plain scalar in flow context) to block form; corrected a stray Cyrillic glyph and a duplicate `setup:` key.

P2 (30 instances: validations 13 real + 4 stubs; endpoints 11 real + 2 stubs) — no SCAFFOLD.yaml edits. Findings: §1.4's declared PRIORITY CONFLICT PAIR 2 (11.4 readiness vs 15 capacity on `/induction-bookings/{id}/confirm`) is **structurally unreachable** — a NOT_READY unit always derives `INDUCTION_FROZEN` and `/confirm` requires posture in {OPEN, RATIO_STRAINED}, so rung 8.02 answers first; documented in a stub rationale rather than faked. Coverage chains must use `role_slot: BEDSIDE` + ADVANCED cert (capacity 4.0), because a CHARGE slot yields min(3.0,4.0)-1.0 = 2.0 which silently overflows to 2.3 on the ACTIVE_FIRST_STAGE re-price and manufactures an unintended COVERAGE_BREACH cascade. `due_at_sequence_anchored` is null for steps 2..4 of a fresh activation while activation anchoring already has 06:10/06:25/06:45/06:55.

P3 (32 instances: errors 13+3, rbac 5+2, cross_cutting_complexity_layers 3+2, consistency_model 2+2) — no SCAFFOLD.yaml edits. Every distinct §1.6 id is now exercised across §1.8+§1.9 (the 3 unreferenced `ERR_*` tokens are prose fragments in naming-convention notes, not ids). Verified globally: `§1.8 unique names: 18 | §1.9 unique names: 110 | stubs: 29 | duplicates: 0`, every `excluded_because.difficulty_instance` and in-prose citation resolves to a real instance in the correct section, no stub carries a `test_recipe`.

Two linter rules P3 had to remediate across all three parts (worth carrying forward): **(d)** you may not `captures:` from an endpoint whose `output:` is a computed-read pseudo-entity absent from §1.1 (`ReadinessReport`, `CoverageReport`, `CapacitySummary`, `SweepResult`) — 60 violations incl. two pre-existing in P1/P2, fixed by deleting the capture blocks and restating each expectation as a prose assert naming the endpoint and its exact field/value; **(e)** `expected_*_version` must be a `${var}` captured from a prior response, never a literal — one pre-existing `expected_unit_version: 1` fixed by inserting a version-capturing GET immediately before the `hold-capacity` call.

Final lint verdict (verbatim):
```
Coverage
  §1.5 endpoints declared:    101
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     81
  Calls scanned (§1.8+§1.9):  1586

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy shared files — 2026-09-04T00:29:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes). Run out of order relative to Step 4's launch (it was copied while Step 2's later passes were still running) so that Step 6 would have it available the moment Steps 5/6 launch; no dependency was violated.

## Step 4: Generate PRD — 2026-09-04T04:20:00.000Z

ORCHESTRATOR NOTE: Step 4 was launched concurrently with Step 2's §1.9 passes. This is safe and intentional — the PRD depends only on SCAFFOLD.yaml (complete at that point), and the doc generator is forbidden to read either design file, so the concurrency also gave it partial physical isolation from SCAFFOLD_CORNER_DESIGN.yaml while that file was still being written.

Subagent summary (verbatim):

PRD generation is complete and verified.

**Output**: `workspace/PRD.md` — **573 lines**, written in 17 append-only heredoc chunks (never a single giant write); no truncation, no re-emitted content.

Section outline: `# Perinatal Safety Ops API — PRD` (1) · `## 1. Introduction` (3) · `## 2. Global Specifications & System-Wide Principles` (11) with 2.1 RBAC (13), 2.2 API Response Structure (29, incl. the two fixed `####` subheads at 31/56), 2.3 Pagination (78), 2.4 Chart Identity and Revision Counters (84), 2.5 The Unit Clock and the Capacity Sweep (92), 2.6 Order of Refusal (100), 2.7 Interval Arithmetic: Two Deliberately Different Conventions (144), 2.8 Rounding, Precision and Boundary Conventions (150), 2.9 Segregation of Duties (158), 2.10 Immutability, Terminal States and Frozen Records (164) · `## 3. Business Logic & Workflows` (170) with 3.1 Standing Up a Unit (172), 3.2 Rostering the Floor (184), 3.3 What Coverage Costs (196), 3.4 The Labor Phase Ladder (220), 3.5 Booking Inductions Against a Finite Bed-Minute Budget (246), 3.6 Hemorrhage and Hypertension Bundles (264), 3.7 Reading the Strip (284), 3.8 Decision-to-Incision (300), 3.9 Debriefs, Visitors and the Quality Ledger (324) · `## 4. Endpoint Definitions` (346) · `## 5. Error Code Catalogue` (454).

Coverage cross-check (scripted against SCAFFOLD.yaml):
- Endpoints: 101 table rows vs 101 scaffold endpoints, **0 missing, 0 extra** (method+path set equality).
- Errors: 116 catalogue rows; all 116 ids also appear in §1–§4 prose (**0 silent errors**).
- Transitions: 70 checked; every from/to state name and every precondition `ERR_*` present — 0 gaps.
- Calculations: 15 checked; every numeric constant appears literally in prose — 0 gaps.
- Validations: 36 rows; every `error_id` present — 0 gaps.
- §4 table exactly 4 columns, §5 exactly 2 columns; §3 contains 0 table rows; §2.2 byte-identical to the skill's `section-2.2-response-structure.md`.
- Field coverage: entities 157/157 fields, request_body 82/82, query_params 50/50 — PASS.
- Rule coverage: 36/36 validations, 4/4 OCC rejections, 70/70 transitions, 15/15 calculations, 59 side-effect endpoints + 36 applies_to scopes, 157/157 entity fields, 8/8 sibling-branch symmetry groups — PASS.
- Path purity (§3 only): 1576 backtick tokens scanned, 0 paths / 0 bare methods / 0 method+path tokens — PASS.

Two post-verification fixes applied by targeted Edit: the six snapshot measure fields (`ntsv_cesarean_numerator`/`_denominator`/`_rate_pct`, `episiotomy_*`) were put in backticks in §3.9 where they had been only narrative; one §1 phrase was reworded off the word "simultaneously" so no OCC-adjacent framing survives.

Read constraint honoured: only SKILL.md, section-2.2-response-structure.md and SCAFFOLD.yaml were opened; neither design file nor any sibling task dir was read.

ORCHESTRATOR VERIFICATION of the known truncation failure mode: `tail -c 400 workspace/PRD.md` ends on the final row of the §5 error table (`| ERR_MEASURE_PERIOD_NOT_CLOSED | 409 |`) — a real section boundary, not mid-sentence. 27 markdown headings present. PRD accepted without regeneration.

## Step 6: Generate implementation — 2026-09-04T09:15:00.000Z

ORCHESTRATOR NOTE: Steps 5 and 6 were launched as concurrent background subagents (Step 5 first, Step 6 seconds later in the following message). At Step 6's spawn `test_suite/` contained nothing but an in-progress conftest, and Step 6 was explicitly forbidden to read `test_helpers/` or `test_suite/`; its final report confirms it never did. Step 6 finished first; Step 5 was still translating queue B.

Subagent summary (verbatim):

Implementation complete and boot-verified.

**Location**: `workspace/implementation/` — 28 Python modules, 5736 lines, plus `start.sh` (executable) and `requirements.txt` (`flask>=2.0`). No `_impl_progress.md`, no `__pycache__`, nothing outside this directory written or read.

**Modules** — Infrastructure: `app.py` 62, `errors.py` 139 (all 116 error ids + `ApiError`), `pipeline.py` 140, `fields.py` 187, `store.py` 81, `clock.py` 111, `const.py` 157, `envelope.py` 61, `rev.py` 36, `views.py` 102, `common.py` 32, `calc.py` 836 (the 15 calculations + all derivations/cascades). Blueprints: `bp_clock.py` 32 (2 endpoints), `bp_staff.py` 104 (5), `bp_beds.py` 131 (6), `bp_units.py` 168 (7), `bp_care.py` 170 (4), `bp_shifts.py` 210 (6), `bp_fetal.py` 221 (5), `bp_reviews.py` 229 (7), `bp_passes.py` 178 (6), `bp_snapshots.py` 145 (5), `bp_sweep.py` 288 (1), `bp_drills.py` 303 (9), `bp_cesarean.py` 325 (8), `bp_bookings.py` 328 (9), `bp_encounters.py` 422 (8), `bp_bundles.py` 538 (13).

**Ordered refusal pipeline (PRD §2.6)** — central, not per-endpoint ifs. Every handler opens with `pipeline.begin(roles=, path=, body_refs=, specs=, occ=, scope=)`, which executes priorities 1–7 declaratively in fixed order: auth headers -> role -> path-id existence (with parent-scoping so a mis-nested child 404s on the child's own error id) -> body-id existence -> field types/enums/ranges -> OCC guard -> cross-aggregate scoping. Priorities 8–16 are passed as `run_checks([(priority, callable), ...])`; the runner sorts by priority then declaration order and raises the first failure, so two simultaneous violations are always resolved by the ladder. Sub-bands are floats (`8.08`, `11.1`, `13.21`, `15`). Errors surface through one `@app.errorhandler(ApiError)` producing the §2.2 envelope with `data.error_id` + `data.message`.

**OCC and versioning** — the four `expected_<parent>_version` rules run at priority 6 inside `begin` via `occ=(field, error_id, target_fn)`; mismatch -> 412 with the rule's own error id, before any state-machine or business check. Version bumps go through `rev.touch(record)`, which records the record id in a per-request `flask.g` set, so a record touched several times in one request advances exactly once no matter how many cascade hops reach it.

**Clock and sweep drivers** — logical clock starts at `2026-08-01T00:00:00Z`; `POST /_clock/set_current_utc` only moves the instant (mutates no entity, bumps no version). All elapsed-time consequences are realised by `POST /obstetric-units/{unitId}/capacity-sweep`, which freezes posture and the turnover buffer up front, then runs the six pinned booking steps (turnover clearing -> hold expiry -> bumped settlement -> promotion -> single posture re-derivation), settling the three other overdue classes (checklist misses, escalation breaches/re-arms, pass expiry) between steps 4 and 5, and returns the 16-field `SweepResult`.

**Endpoint count** — `app.url_map` diffed against SCAFFOLD.yaml: **101 declared / 101 served, missing [], extra []**. The only undeclared route is `GET /_health`.

**Boot verification** — `PORT=34291 bash start.sh` from a fresh process; `/_health` -> `{"status":"ok"}`; all 15 collection GETs on a fresh boot return `response_type: "array"` with `total_count: 0`, confirming zero seeding. A driver run exercised unit/bed/staff/drill/shift/booking creates (201), activate/document/validate/hold-capacity/sweep (200), readiness/coverage/capacity-summary reports, sweep promotion (`promoted 1`, bed `LDR-00` -> `HELD`), plus deliberate failures: 403 `ERR_INSUFFICIENT_PERMISSIONS` for a wrong sweep role and 404 `ERR_UNIT_NOT_FOUND` for an unknown unit, both in the correct envelope. All 28 modules `py_compile` clean; grep for `sqlite|open(|json.dump|tempfile|/tmp|pickle|shelve` found no persistence. Server killed by its own PID from `lsof -t -i :34291 -sTCP:LISTEN`; port confirmed free. No broad `pkill` was ever used.

**Ambiguous PRD points and interpretations chosen** (these are the prime Step 8/9 targets):
1. §3.10 sweep ordering — only the six booking steps are pinned. Checklist misses, escalation chains and pass expiry settle between steps 4 and 5, so a breach-driven cascade bump frees capacity before promotion, while posture is re-derived exactly once at the end.
2. §3.6 gate-reached — gate-1 checklist items count as gate-reached while the activation is `ACTIVATED` (the same exception the PRD grants completion); otherwise an untouched bundle could never record a miss.
3. `breached_encounter_ids` (SweepResult) — reports only encounters whose `staffing_state` actually moved into `COVERAGE_BREACH` during the sweep, per the SCAFFOLD field text, not encounters with escalation breaches.
4. "No record is touched" vs `last_capacity_sweep_at` — read as applying to the swept obligation records; the sweep always writes `last_capacity_sweep_at` and therefore always bumps `unit.version`.
5. Drill currency — re-derived inside the sweep before readiness/posture, since it is a pure function of elapsed time and readiness reads it.
6. Unspecified sub-orderings, chosen deterministically: holds by `hold_expires_at` then `created_at`; bumped by `requested_start_utc` then `created_at`; promotion beds by `bed_label` ASC; items by `step_sequence` within activations by `activated_at`; assessments by `assessed_at` within encounters by `created_at`.
7. Boundary senses, aligned with sibling handlers: hold expiry and turnover clearing inclusive (`<= now`), pass expiry inclusive (check-in requires `now < valid_until`), escalation deadlines strict (`now > due`).

Not exercised end-to-end: sweep step 2 (`TURNOVER` -> `AVAILABLE`), which needs the full delivery/discharge path to reach `TURNOVER`; its 12 lines follow the same pattern as the verified steps.

## Step 5: Generate unit tests — 2026-09-04T13:40:00.000Z

Subagent summary (verbatim):

Done. The last queue-B module is written and the whole suite passes its audits.

**Final module**: `test_suite/test_63_sweep_driven_edges_wait_for_the_sweep.py` (595 lines, 18 tests) translates `Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep`. One unit with a validated drill (so the `NOT_READY` freeze branch does not block the hold), one uncovered TIER_I/ANTEPARTUM walk-in holding the unit on `RATIO_STRAINED`/buffer 75, a `MEDICALLY_INDICATED` `POST_DATES_41W` booking holding LDR-01 with a frozen projection of 675 (600 + 75) against the 2026-08-02 ledger, and a `PARTNER` pass whose `valid_until` is 2026-08-02T06:00:00Z. Three arms: a full day of clock advance with no sweep changes nothing; one sweep names exactly `holds_expired_booking_ids == [booking]` and `expired_pass_ids == [pass]` with the other seven arrays empty and the next reads already final; the second identical sweep is a no-op with no double credit.

One adjudication: the recipe plants the pass exactly on `valid_until` and sweeps at that instant. PRD 334 governs the sweep edge with "once `valid_until` has passed", which does not uniquely derive an outcome at the boundary itself (the inclusive-boundary sentence in that line governs *check-in*, not the sweep). I therefore moved the trigger clock to `2026-08-02T06:01:00Z`, strictly past both deadlines, keeping the whole instance intact rather than asserting an underdetermined boundary. The hold side needed no adjustment (PRD 96 step 3 and PRD 258 are explicitly inclusive). Also dropped `reentry_count == 0` and the drill's `measured_d2i_minutes` from an initial draft — PRD-silent initial values.

**Whole-suite audit (all green)**
- **512 tests** across 63 modules, `test_suite/` 21,433 lines; `test_helpers/` 2,823 lines.
- Design-tag audit (AST-based): 512 collected == 512 tagged, exactly one `Design:` line per test, always the last docstring line, zero unknown tags, zero tags pointing at `excluded_because` stubs.
- Instance coverage: all **18/18** §1.8 (queue A) instances have >=2 tests; all **81/81** non-stub §1.9 (queue B) instances have >=1 test; **0 instances skipped**. The 29 stubs produced no tests and all 29 `difficulty_instance` cross-references resolve.
- Citations: `checked 619 bad 0` — every quoted fragment is a verbatim, non-abbreviated PRD sentence. No file mentions "scaffold".
- Hygiene: pyflakes silent; `pytest --collect-only -q` -> 512 collected, 0 errors; no `skip`/`xfail` anywhere; every refusal read as `response.json()["data"]["error_id"]`.

**Placement proof**: `test_helpers/` and `test_suite/` are at the TASK ROOT; `find workspace -maxdepth 2 -name test_helpers -o -name test_suite` returns nothing; `workspace/` holds only INSTRUCTION.md, PRD.md, implementation/. Nothing under `workspace/implementation/` was read or touched.

**Coverage audit notes**: probes were dropped or re-aimed only where the PRD contradicts or is silent on the recipe's asserted outcome (recipe-defect discipline), never weakened into placeholders — readiness-report `rolling_event_ids` / `or_standby_staffed` / `MEAN_D2I_ABOVE_*` reason codes and `readiness_reason` non-nullness (PRD names no such fields/values; the window-membership claim is discriminated through the rolling mean instead), drill `revision_count` and pass `reentry_count` initial values, `escalation_tier_high_water == 0` at creation, and the exactly-on-`valid_until` sweep expiry above. Intra-priority-8 conflicts where the PRD does not name the id are asserted as `validate_error_is_one_of([specific, ERR_INVALID_STATE_TRANSITION])` plus a separate status assert; cross-band conflicts assert the earlier band exactly with `!=` checks against the later ones. Module numbering has a gap at `test_19` (consolidated during generation) — not a missing instance.

## Step 7: Run tests and iterate — 2026-09-04T09:50:00.000Z

ORCHESTRATOR VERIFICATION (the known failure mode where a Step 7 agent reports a clean sweep with no artifacts behind it): I re-read all eight `workspace/implementation/results.$i.json` myself. Eight files present, each `{'total': 512, 'passed': 512, 'failed': 0, 'errors': 0, 'skipped': 0}`, all mtimes within 1 second of each other (2026-09-04T09:47:20–21) — consistent with one genuine concurrent 8-round sweep, not a serial re-stamp. Accepted.

Subagent summary (verbatim):

All 8 rounds are green. The loop is closed.

**Iterations run: 2** (iteration 1 = 445/512 in all 8 rounds with 67 deterministic failures; iteration 2 = clean).

### Tests deleted
None. One test was **split** under STEP 1c rather than deleted:
- `test_suite/test_08_record_delivery_cascade.py::test_the_operating_room_bed_clears_against_the_current_turnover_buffer` — **non-unique derivability**. The two assertions `coverage_deficit_units == 4.0` and `staffing_posture == "INDUCTION_FROZEN"` after the `REVIEW_PENDING` walk-on are not decidable from the PRD: "`TIER_IV` fires when … `DECISION_DECLARED`, `TEAM_MOBILIZED` or `INCISION_RECORDED`" + "and to false otherwise" gives 0.5/RATIO_STRAINED, while "Closing … drops the encounter from the in-theatre clause of the posture derivation" keeps 4.0/INDUCTION_FROZEN alive until `CLOSED`; the record-delivery paragraph names no re-derivation at all. Dropped those two; kept the traceable remainder (`turnover_clear_at` 10:15, bed `TURNOVER`, buffer 75, plus the newly explicit `posture != "OPEN"`, which both readings share).

### Fixes to `test_helpers/`
- `fixtures.py` — added `READREADINESS_DRILL_STAFF`/`lift_unit_off_not_ready()` (new factory: schedules, starts, documents and validates one drill) because PRD 3.1 opens every unit at `NOT_READY` and PRD 3.3 freezes inductions on exactly that, so a fixture cannot claim `OPEN` without a validated drill.
- `fixtures.py` — `setup_validated_drill` callers' scheduling instants corrected via the same helper's `_instant/_spell` arithmetic, since "the boundary instant counting as due" forbids starting a drill before `scheduled_for_utc`.

### Fixes to `test_suite/`
| file | test | why |
|---|---|---|
| test_03, test_04, test_05, test_11, test_17 | fixtures | drill-less unit is `INDUCTION_FROZEN` per PRD 3.3; call `lift_unit_off_not_ready` first |
| test_15, test_18 | fixtures | drill was started 5 min before `scheduled_for_utc` -> `ERR_DRILL_NOT_DUE` |
| test_50 | `test_a_backwards_incision_still_answers_at_the_roster_band` | ladder puts 11.4 above 14.1 and §2.6 lists no reversal |
| test_58 | `test_the_refused_mobilisation_wrote_nothing_on_either_unit` | a `DECISION_DECLARED` event makes the encounter `TIER_IV`, hence one-to-one `True` |
| test_32 | `test_the_rejected_creation_wrote_no_unit` | `assert <Response [400]>` is always false; assert `status_code == 400` |
| test_33 | `test_the_context_field_rung_sits_below_the_revision_guard` | row was re-read after the fixture's own successful rescission; capture it before |
| test_46 | `test_the_first_gate_one_step_lands_on_time_and_starts_the_stage` | `highest_stage_reached` is 1 in stage 1 (gate check + "1 or less") |
| test_55 | `test_the_barred_documenter_still_collects_the_currency` | iterated dict keys instead of `.values()` |
| test_08 | as above | STEP 1c split |

### Fixes to `implementation/`
| file | function | why |
|---|---|---|
| `views.py` | `FIELDS["units"]` | PRD 3.8: the unit "publishes `cesarean_readiness_state`, `readiness_reason`, `current_drill_id`, `current_drill_expires_at` and `mean_d2i_minutes`" |
| `bp_units.py` | `create_unit` | seed those four public keys instead of a private `_readiness_reason` |
| `calc.py` | `rederive_unit` | write the four readiness fields publicly |
| `calc.py` / `bp_encounters.py` | `rederive_encounter(bump_self=)` / `create_encounter` | PRD 2.4: `version` "starts at 1 when the record is created" — the creation-time derivation must not bump its own subject |
| `bp_beds.py` | `retire_bed` | PRD 3.2 names `ERR_BED_HAS_FUTURE_HOLDS`; merged into one band so it precedes the source-state guard (a held bed would otherwise make it unreachable) |
| `bp_shifts.py` | `cancel_shift` | PRD 3.3 names `ERR_SHIFT_HAS_ACTIVE_COVERAGE` ahead of the generic transition refusal |
| `bp_cesarean.py` | `mobilize_team` | dropped the invented `ERR_SHIFT_NOT_ACTIVE` check; the roster requirement belongs inside `ERR_CESAREAN_TEAM_INCOMPLETE` at 11.4 |

### Final sweep evidence (8 concurrent rounds, `--isolation per-test-server`, launched with `setsid nohup`)
All 8 rounds 512/512 passed, 0 failed, 0 errors, 0 skipped. Eight distinct `results.$i.json` artifacts, ~989 s per round, every one of the 4096 test executions `status: "passed"`. Notes at `workspace/step7_notes.md`.

## Step 8: Finalize PRD — 2026-09-04T09:57:00.000Z

ORCHESTRATOR VERIFICATION: `diff PRD.md PRD_FINALIZED.md` returns 32 lines (8 revised paragraphs), 141,940 -> 145,040 bytes — the pass genuinely ran and is a minimal patch, not a copy.

Subagent summary (verbatim):

`PRD_FINALIZED.md` is written. 8 lines changed, all surgical in-place edits. `PRD.md` 573 lines / 141,940 bytes; `PRD_FINALIZED.md` 573 lines / 145,040 bytes; line delta 0.0% (8 lines revised in place), byte delta **+2.2%**, word delta +2.4%.

**Changes**
- **§3.1 (unit creation)** — insert — the four readiness fields now have declared creation values: `readiness_reason` at `NO_CURRENT_DRILL`, `current_drill_id`/`current_drill_expires_at`/`mean_d2i_minutes` null — `bp_units.py:57-60`
- **§3.8 (readiness derivation, last paragraph)** — revise — states the five fields are published on the unit resource itself and enumerates the `readiness_reason` vocabulary in branch order (`NO_CURRENT_DRILL`, `MEAN_D2I_ABOVE_DEGRADED_CEILING`, `NO_OR_STANDBY`, `MEAN_D2I_ABOVE_READY_CEILING`, `READY`) — `calc.py:340-356`, `views.py:11-12`
- **§3.1 (bed retirement)** — revise — pins the guard order: `ERR_INVALID_STATE_TRANSITION` for an already-`CLOSED` bed, then `ERR_BED_HAS_FUTURE_HOLDS` **before** the source-state guard, then `ERR_BED_NOT_RELEASABLE` — `bp_beds.py:112-125`
- **§3.2 (shift cancellation)** — revise — `ERR_SHIFT_HAS_ACTIVE_COVERAGE` is evaluated ahead of the source-state check, falling back to `ERR_INVALID_STATE_TRANSITION` once no row is `ACTIVE` — `bp_shifts.py:198-206`
- **§3.6 (checklist completion)** — revise — the first gate-1 completion raises `highest_stage_reached` from 0 to 1 (satisfying the gate check directly, still inside the rescind "1 or less" window) — `bp_bundles.py:279-282`
- **§3.5 (induction admission)** — insert — an admission-minted encounter is readable at `version` 2, against `version` 1 for the walk-in mint — `bp_bookings.py:222/253`, `bp_encounters.py:76`, `calc.py:465-467`
- **§3.8 (record delivery)** — insert — the self-advance to `REVIEW_PENDING`/`CLOSED` is fed back: neither status fires the in-theatre `TIER_IV` clause, so encounter acuity/one-to-one/required-coverage/review flag are recomputed, coverage rows re-priced and unit deficit/posture/buffer re-derived at the end of the request — `bp_cesarean.py:259-264`, `calc.py:449-485`, `const.py:92`
- **§3.8 (cesarean close)** — revise — removed the false implication that a `REVIEW_PENDING` event sat in the in-theatre clause; a `CLOSED` event is outside it "exactly as `DELIVERED` and `REVIEW_PENDING` already were", and close runs the same full re-derivation — `bp_cesarean.py:291-293`, `calc.py:181`

**Per-edit pre-edit search log**
1. **Unit creation defaults.** Subject: the four readiness fields at unit birth. Enumerated: `bp_units.py:create_unit` (only seeder), `calc.py:rederive_unit` (only later writer), `views.py FIELDS["units"]`, `bp_units.py:readiness_report`. Verified empirically that `POST /obstetric-units` returns `readiness_reason=NO_CURRENT_DRILL`, three nulls, `version` 1, posture `OPEN`. (c) Added "for the same reason" rather than tying the nulls to any branch, since `rederive_unit` may later set them from any branch.
2. **`readiness_reason` vocabulary.** Subject: reason code enum. Enumerated: `calc.py:readiness_view` (sole producer, 5 codes), `create_unit` seed, `readiness_report`, `posture_view`'s separate `_posture_reason` codes (distinct field — no collision). (c) Wrote "in that branch order" and left existing branch prose untouched so the two descriptions cannot drift.
3. **Bed retirement order.** Subject: retire_bed guards. Enumerated: `bp_beds.py:retire_bed` (108-132), `patch_bed` (the other `ERR_BED_NOT_RELEASABLE` producer, 89-99), grep for `ERR_BED_HAS_FUTURE_HOLDS` (single site). (c) Scoped the new sentences explicitly to retirement and added "and carries no such booking" so the blocking-path prose at the same PRD line stays true.
4. **Shift cancellation order.** Subject: cancel_shift guards. Enumerated: `cancel_shift` (sole `ERR_SHIFT_HAS_ACTIVE_COVERAGE` producer), `calc.active_care_on_shift`, `bp_shifts.py:relieve`. (c) Wrote "released or superseded" rather than just "released", because a one-to-one handoff can leave rows `SUPERSEDED`.
5. **`highest_stage_reached` = 1.** Subject: that counter. Enumerated: `bp_bundles.py:100` (init 0), `255` (gate check), `281-282` (max(1,…)), `343` (escalate), `439` (`_void_pending`), `446` (debrief walk-on `>= 2`), `511` (rescind `<= 1`), `bp_sweep.py:141`. (c) Added the two consequence clauses without asserting the value is set anywhere else.
6. **Admission-minted encounter version.** Subject: encounter `version` at creation. Enumerated: `bp_encounters.py:76` (`bump_self=False`), `bp_bookings.py:253` (default `bump_self=True`), `calc.py:465-467`, `store.py:31-41`. Confirmed by driving the real app in-process: walk-in `version` 1, admission `version` 2. (c) Confined the claim to the two encounter mints; did NOT touch §2.4's global "starts at 1", to avoid asserting a universal that other cascade-minted rows would contradict.
7. **Record-delivery re-derivation.** Subject: the derivations after the `DELIVERED` walk-on. Enumerated: `record_delivery` (264), `calc.rederive_encounter`, `calc.derive_acuity`'s `CESAREAN_IN_THEATRE` clause, `const.CESAREAN_IN_THEATRE`, `calc.derive_review_required`, `rederive_unit`. (c) Named the exact recomputed fields and wrote "An encounter whose only `TIER_IV` ground was the operation" rather than a blanket "falls to `TIER_I`", so encounters still held at `TIER_III`/`TIER_IV` by a bundle, magnesium or a `CATEGORY_III` chain are not mis-described.
8. **Cesarean close.** Subject: the in-theatre clause on close. Enumerated: `close_event` (293), `calc.live_cesareans` / `const.CESAREAN_NON_TERMINAL` vs `CESAREAN_IN_THEATRE`, `calc.derive_review_required`, `posture_view`. (c) Rewrote the claim as "outside the in-theatre clause of the **acuity** derivation" — the original "posture derivation" is wrong on every path, since posture only sees the cesarean indirectly through the encounter's requirement — and softened to "normally finds nothing left to move", because a close from `DELIVERED` can still change `review_required`.

## Step 9: PRD completeness scan — PRD_COMPLETED.md — 2026-09-04T11:00:56.000Z

ORCHESTRATOR DECISION: Step 9 was run as **three sequential file-partitioned passes** rather than one subagent, for the same 64000-output-token reason that partitioned Steps 2/4/5/6 — the implementation is 28 modules / 5736 lines and a single-agent scan of all of them against a 573-line PRD reliably dies at the cap with nothing on disk. Each pass owned a disjoint slice of `workspace/implementation/`, read `PRD_COMPLETED.md` as it stood after the previous pass, and edited it in place with `Edit` (never `Write`). Pass A seeded `PRD_COMPLETED.md` from `PRD_FINALIZED.md`. Pass C additionally carried the whole-document consistency duty. Per the skill, no pass was given `SCAFFOLD*.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or this `worklog.md`.

ORCHESTRATOR VERIFICATION (both known silent-failure modes checked directly, not taken from the subagents' reports):
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` → **288 diff lines / 73 changed paragraphs**; 145,040 -> 184,056 bytes (+26.9%). The file is a real patch, NOT byte-identical to `PRD_FINALIZED.md`, so the scan genuinely ran.
- Structure preserved: 573 lines, 27 headings, 5 top-level sections, 221 table rows — identical counts to `PRD.md` and `PRD_FINALIZED.md`. All growth is in-paragraph.
- §5 catalogue holds **116** error ids, set-identical to those raised in `implementation/errors.py`.
- Tail intact at a real section boundary: `| ERR_MEASURE_PERIOD_NOT_CLOSED | 409 |` — not truncated mid-sentence.
- Implementation untouched by Step 9: newest `implementation/*.py` mtime 09:20, newest test-file mtime 09:29, both older than the sweep artifacts (`results.*.json`, 09:47:20–21). The 8×512/512 green sweep therefore still describes the code as it stands.

Pass summaries (orchestrator-recorded; the three subagents' verbatim reports were lost to a context compaction between Pass C and this entry, so the figures below are transcribed from the orchestrator's own running notes at the time each pass returned):

**Pass A** — `app.py`, `envelope.py`, `errors.py`, `pipeline.py`, `fields.py`, `store.py`, `clock.py`, `const.py`, `rev.py`, `views.py`, `common.py`, `calc.py`, `bp_clock.py`. **23 edits** = 18 ambiguity-pins + 5 mismatch-revisions. 145,040 -> 151,774 chars.

**Pass B** — `bp_units.py`, `bp_beds.py`, `bp_staff.py`, `bp_shifts.py`, `bp_care.py`, `bp_encounters.py`. **31 edits** = 20 pins + 11 revisions. 151,774 -> 161,926 chars. Handed Pass C an explicit carry-forward note: do **not** re-tighten the §3.5 "elective / patient-request only" universal, because `bp_encounters.py:316` bumps every priority class on the second-stage freeze cascade.

**Pass C** — `bp_bookings.py`, `bp_bundles.py`, `bp_fetal.py`, `bp_cesarean.py`, `bp_drills.py`, `bp_reviews.py`, `bp_passes.py`, `bp_snapshots.py`, `bp_sweep.py`, plus the final whole-document consistency duty. **57 edits** (52 net distinct) = 34 pins + 18 revisions. 161,926 -> 184,056 chars. Three cross-section contradictions resolved:
- §3.7 sweep breach cascade narrowed to the elective / patient-request classes, per `bp_sweep.py:194` (consistent with Pass B's carry-forward note, which concerns a different cascade in `bp_encounters.py`).
- §3.9 certification wording "decided first of all" reworded to sit **after** the declared-transition guard, matching the actual guard order.
- One wrong intra-document section cross-reference corrected.

TOTAL across the three passes: **111 edits** (72 ambiguity-pins, 34 mismatch-revisions, 3 contradiction resolutions, 1 cross-reference fix; 5 of Pass C's edits were later-superseded rewrites of the same paragraph, hence 52 net distinct there).

Pipeline complete. `workspace/PRD_COMPLETED.md` is the final contract.
