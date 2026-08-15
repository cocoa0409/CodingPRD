# Worklog — task_1303_construction_equipment_fleet_utilization

## Step 1: Create Task Directory — 2026-08-12T00:00:00.000Z

Task directory `tasks/task_1303_construction_equipment_fleet_utilization/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Resume Assessment — 2026-08-12T00:00:00.000Z

Prior run terminated during Step 2. Found: SCAFFOLD.yaml (1802 lines, valid YAML, all §1.1–§1.7 sections present — 11 entities, 9 state machines, 2 concurrency rules, 10 calculations, 21 validations, 68 endpoints, 21 errors, 4 roles; no scaffold_difficulty_design / scaffold_corner_design keys). Missing: SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/INSTRUCTION.md, PRD.md, test_helpers/, test_suite/, implementation/. Decision: keep SCAFFOLD.yaml; regenerate the two missing design indices (Step 2 continuation), then proceed Steps 3–9.

## Step 2 (resume): Generate missing design indices — 2026-08-12T00:00:00.000Z

Done. Both missing design indices were generated, fully grounded in the existing `SCAFFOLD.yaml`, with a clean lint verdict.

**Files written**
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — top-level key `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — top-level key `scaffold_corner_design:`

**Instance counts**
- Difficulty design: **23 instances across all 9 rules** (dual_variant_calc 3, combinatorial_formula 3 covering modes (a)/(b)/(c), non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 3)
- Corner design: **74 instances across 9 sections** (entities 17, state_machines 16, calculations 12, validations 9, endpoints 4, errors 2, rbac 5, cross_cutting_layers 6, consistency_model 2), of which 10 are `excluded_because:` stubs citing §1.8 instances and 64 carry full test recipes
- Total structured calls replayed/linted: 724

**Verification**
- `scaffold_lint.py`: `VERDICT: clean lint` (endpoint resolution, roles, payload shapes, capture paths, OCC dynamic-version rule, FK reverse reachability)
- Separate audit pass: zero duplicate instance names across both files, zero unbound `${var}` placeholders, all `grounds:` refs resolve to declared §1.1–§1.7 elements, all `excluded_because:` stubs cite existing difficulty instances
- All formula-derived assert literals were executed in Python with round-half-up semantics (e.g. allocated 25004/26664/26000, own 52000/60800, residual 2950000 vs 4375000, utilization 4286 vs 5000, damage per-line 10 vs sum-then-round 9, burn rates 1000/1750/1050, TIE at 14200)

**Noteworthy design decisions**
- The deepest instances exploit a subtle state-space edge in the scaffold: an assignment stays SUSPENDED after repair when its project is SUSPENDED, leaving equipment IDLE with a live non-terminal assignment — the *only* path that makes `ERR_ASSIGNMENT_OVERLAP` (priority 10) and `ERR_TRANSPORT_PENDING` (priority 17) reachable at all. Both are exercised as full recipes.
- Overlap instances use genuinely different interval geometries: half-open day-granularity assignment windows (adjacency allowed) vs closed timestamp lowboy windows with a 4-hour turnaround buffer (departure exactly at `arrive+4h` allowed).
- Combinatorial instances span all three §0.5 modes: pinned weekend-then-idle multiplier stacking (a), per-line-vs-sum-then-round damage rounding with a 1-cent divergence (b), and the pinned evaluation order of `own_vs_rent` consuming `rental_allocation` outputs (c).
- OCC tests use only `${var}` or `${var} - 1` version references (never literals), and the `every_error_code_has_a_trigger` instance audits all 21 §1.6 error ids back to named instances.

## Step 3: Copy Shared Files — 2026-08-12T00:00:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-12T00:00:00.000Z

All contracts pass. The PRD is complete and verified.

**Output:** `workspace/PRD.md` — 325 lines; §1 Introduction (3 paragraphs), §2 with 10 subsections (2.1–2.10), §3 with 9 subsections (3.1–3.9), §4 endpoint table (68 rows = all 68 scaffold endpoints), §5 error catalogue (21 rows = all 21 scaffold errors).

**Coverage confirmation:** all scaffold sections are projected into prose — 11 entities (73 fields), 9 state machines (all transitions, preconditions, side effects), 10 calculations (rental_allocation, own_vs_rent, utilization_rate, redeployment_scan, damage_chargeback, residual_value, service_threshold, transport_overlap, budget_guard, fuel_burn_rate — all constants pinned: 900/4200/1500 cents, 15000 bp abuse multiplier, 5000000 cap, 4-hour turnaround, 8-hour day, 5-day idle window), all 21 validations with priority order (§2.7) and error pairing, both OCC rules, all 68 endpoints, all 21 errors, all 4 roles with identity semantics.

**Hard Contract Reports:**

Field coverage: entities[].fields 73/73, endpoints request bodies 57/57 — PASS
Rule coverage: 21 validations in priority order, 2 OCC rules, 45 state transitions, 10 calculations, all side effects, field-level defaults/nullability/enums, 9 sibling-branch symmetry groups — PASS
Path purity (§3): 433 backtick tokens scanned, 0 paths/methods leaked — PASS

§2.2 verified byte-identical to `section-2.2-response-structure.md`. Forbidden design-index files and all other task_* directories were never opened.

## Step 5: Generate Unit Tests — 2026-08-12T00:00:00.000Z

**Files written** — `test_helpers/`: `__init__.py` (barrel export), `types.py` (11 entity TypedDicts + status enums; AssignmentCharge/TelematicsReading omit updated_at/version per PRD §2.4), `api_client.py` (~50 methods, one per PRD §4 endpoint), `api_errors.py` (21 ApiErrorId values + HTTP map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`. `test_suite/`: `conftest.py`, `test_01_creation_and_listings.py` (15), `test_02_validation_and_rbac.py` (21), `test_03_state_machines.py` (18), `test_04_calculations.py` (21), `test_05_thresholds_cascades.py` (42), `test_06_occ_and_consistency.py` (10).

**Test counts per queue**
- Queue A (Difficulty): 23 instances × 2 tests each = 46 tests — all 23 §1.8 instances covered.
- Queue B (Corner): 62 non-stub instances × ≥1 test = 81 tests.
- Total: 127 tests, all collected cleanly by pytest.

**Skipped instances (one-line reasons)**
- 10 corner stubs with `excluded_because:` — not translated per skill spec.
- `Corner/errors/every_error_code_has_a_trigger` — meta-audit instance with empty setup/trigger; not translatable to an executable API test (gap left as gap).

**Design-tag contract confirmation** — all 127 docstrings end with exactly one verbatim `Design: Difficulty/...` or `Design: Corner/...` line; programmatic audit confirms every tag resolves to a real instance; every docstring carries a verbatim PRD citation (≥6-word grep-match after normalization); no skip/skipif/xfail anywhere.

## Step 6: Generate Implementation — 2026-08-12T00:00:00.000Z

**Files written** (all under `workspace/implementation/`): `start.sh` (guarded launcher, foreground, 0.0.0.0:$PORT default 10000), `requirements.txt`, `app.py` (app factory, envelope handlers), `db.py` (in-memory store, empty at boot, logical clock default 2026-08-01T00:00:00Z), `errors.py`, `response.py`, `middleware.py` (X-User-ID/Role auth), `util.py` (validators, pagination, round-half-up), `logic.py` (all 10 calculations), `routes/` (11 modules: clock, classes, equipment, readings, projects, assignments, workorders, mechanics, lowboys, transport, damage).

**Endpoint count** — all 66 endpoints from the scaffold endpoint table implemented (68 route registrations incl. health route).

**Key behaviors verified by live smoke runs** — assignment lifecycle with OCC (412), budget guard (inclusive ≤), half-open overlap (adjacent allowed); close math traced numerically (weekend/idle mixing, suspension dropping billable days, elapsed-vs-billing utilization divergence, AssignmentCharge without version/updated_at); telematics duplicate 409, threshold cross → auto PREVENTIVE WO, void → un-cross → WO auto-cancelled, inclusive fuel window; mark-down SUSPENDED cascade; repair complete → DOWN→IDLE + earliest-created SUSPENDED reactivation with project-OPEN check; damage flow (ERR_PROJECT_MISMATCH, per-line rounding, dispute/reassess OCC, confirm budget gate); transport origin-site gate, buffered +4h interval conflict boundary; disposal ERR_RENTED_UNIT / ERR_OPEN_WORK, residual verified SALE (9050000) and SCRAP (9988125); redeployment scoring tie-breaks; 5-day inclusive idle alert; fresh boot confirmed (empty store, ~3s ready).

One judgment call: a chargeable day counts as idle only when an ACCEPTED reading with delta 0 exists for that day (days with no reading bill at base/weekend rate), per scaffold's "chargeable days whose accepted engine_hours_delta == 0" wording.

## Step 7: Run Tests and Iterate — 2026-08-12T00:00:00.000Z

**Iterations run:** 2 sweeps (8 parallel rounds each). Sweep 1: 122-123/127 per round; Sweep 2: **127/127 in all 8 rounds — clean exit**.

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule; no PRD-silence or unique-derivability collapses found.

**Fixes applied to test_suite/:**
1. `test_suite/test_02_validation_and_rbac.py` — added `make_lowboy` to the test_helpers import block; `test_same_origin_destination_rejected` and `test_arrive_before_depart_rejected` (PRD §3.5 verbatim rules) used the factory without importing it (NameError, 8/8 rounds).
2. `test_suite/test_05_thresholds_cascades.py` — `_setup_suspended_with_pending_transport` now advances the logical clock to `2026-08-04T09:00:00Z` before the mark-down. Previously activation and mark-down both ran at clock `2026-08-03T09:00`, so under PRD §3.6 ("a calendar day ... is chargeable whenever the assignment was ACTIVE for any part of that day") only 08-03 was chargeable and the implementation correctly computed 5000 (1 idle day × 10000 × 0.5) while the test expected 10000 (2 idle days). The fixture never made 08-04 an ACTIVE day — a setup bug, not an implementation bug. Sibling `test_close_blocked_while_transport_pending` asserts only the 409 and is unaffected.

**Fixes applied to test_helpers/:**
3. `test_helpers/api_client.py` — `ApiClient.__init__` sets `Connection: close` on the shared session. Per-test-server isolation SIGKILLs and respawns the server before every test; a pooled keep-alive connection reused against a dead socket produced a rare ConnectionResetError (round 8, `test_current_version_retry_succeeds`). Fresh TCP per request removes the race.

**Fixes applied to implementation/:**
4. `workspace/implementation/start.sh` — dependency check now stamped behind a `.deps_ok` marker, so each per-test boot spawns one Python interpreter instead of two. The runner's restart poll window is fixed at 15s; under 8-way lockstep restarts plus other tenants' load, the double-interpreter boot intermittently exceeded it, surfacing as "could not be restarted" setup errors (`test_cancel_dispatch_leaves_maintenance_untouched` 8/8, `test_stale_damage_version_rejected` 6/8). No API behavior changed; server still binds $PORT on 0.0.0.0 in foreground.

**Implementation correctness note:** `logic.py` (`compute_close`) needed no changes — its chargeable-day interval-overlap computation was verified PRD-faithful; the observed 5000 was the correct answer for the fixture as originally written.

## Step 8: Finalize PRD — 2026-08-12T00:00:00.000Z

`PRD_FINALIZED.md` written with exactly two inline revisions, both tracing to Step 7 item #2 / the correctness note (idle-day billing semantics in `compute_close`).

**Line counts / delta:** PRD.md 325 lines / 47,828 bytes; PRD_FINALIZED.md 325 lines / 48,084 bytes. +0 lines, +256 bytes (+0.53%). Two inline revisions, no new sections.

**Changes:**
- §3.1 — revise — `idle_day_multiplier_bp` description changed from "applied to any chargeable day on which the unit logged zero engine hours" to "applied to any chargeable day on which an accepted telematics reading records a zero engine-hour delta", removing the reading that a no-reading day "logged zero hours" — `implementation/logic.py:176-179`.
- §3.6 (rental-allocation paragraph) — revise — idle-day clause now reads "if the day is idle — meaning an accepted reading exists for that recorded_date and its engine-hour delta is zero —" and adds: "A chargeable day with no accepted reading is not idle: it bills at the (weekend-adjusted) base with no idle-day multiplier and is not counted in idle_days." — `implementation/logic.py:168-180` (sole billing loop; caller `routes/assignments.py:165`).

**Step 7 items with no PRD edit (harness/fixture plumbing):** #1 test-import NameError fix, #3 `Connection: close` header, #4 `start.sh` `.deps_ok` caching — none touch API behavior.

**Per-edit pre-edit search log:**
- Edit 1 (§3.1): subject = meaning of "idle" for `idle_day_multiplier_bp`; paths enumerated: logic.py:163-181 (compute_close sole consumer), routes/assignments.py:165 (sole caller), routes/assignments.py:124 (activation budget guard, no multipliers), logic.py:259,276 (redeployment raw rate), logic.py:299-313 (fuel_summary chargeability-independent), routes/classes.py:21 (validation only), equipment.py:163 (idle_alert streak — distinct concept); wording scoped to avoid colliding with §3.7 idle-streak.
- Edit 2 (§3.6): subject = per-day idle-multiplier application and billing of no-reading days; paths enumerated: same set plus milli accumulation (logic.py:174-175), weekend-first-then-idle stacking (logic.py:171-179 — already pinned, left intact), no-reading branch (logic.py:169-180); added explicit negative clause rather than redefining existing sentences, keeping already-pinned behaviors verbatim.

## Step 9: Complete PRD — 2026-08-12T00:00:00.000Z

`PRD_COMPLETED.md` written as a minimal patch over `PRD_FINALIZED.md`. Size: 325 lines / 48,084 chars → 325 lines / 51,447 chars. Char delta: +3,338 across 19 edited passages (no lines added/removed; all in-paragraph inserts/revisions, no new sections).

**Counts**: 21 ambiguity-pins, 4 mismatch-revisions.

**Changes:**
- §2.1 — insert — ambiguity — missing X-User-ID also rejected ERR_UNAUTHENTICATED — middleware.py:17
- §2.3 — insert — ambiguity — equal created_at tie-break by creation sequence — util.py:135
- §2.3 — insert — ambiguity — enumerated exact query filters per list endpoint — routes/{equipment,assignments,workorders,transport,damage,projects,lowboys,mechanics}.py
- §2.4 — insert — ambiguity — version starts at 1 at creation — db.py:60-61
- §2.7 (rule 5) — insert — ambiguity — duplicate human codes → ERR_INVALID_REQUEST; unit_tag uniqueness after rule-6 ownership gate — classes.py:27-28, equipment.py:53-54, projects.py:27-28, mechanics.py:28-29, lowboys.py:28-29
- §2.10 — insert — ambiguity — resource created_at/updated_at read the logical clock — db.py:59
- §2.10 — insert — ambiguity — clock may be set backward — routes/clock.py:16
- §2.10 — insert — ambiguity — timestamps without explicit offset interpreted as UTC — util.py:79-81
- §3.1 — revise — mismatch — idle_alert_utilization_bp stored/validated but consulted by no calculation — classes.py:23-39
- §3.1 — revise — mismatch — unit_tag unique across entire registry, not scoped per class — equipment.py:53-54
- §3.1 — insert — ambiguity — acquisition_date/useful_life_months required for RENTED too; positive-value constraints OWNED-only — equipment.py:40-52
- §3.1 — insert — ambiguity — equipment_budget_cents must be non-negative — projects.py:26
- §3.3 — insert — ambiguity — fuel-summary bounds are required query params from_date/to_date — equipment.py:174-179
- §3.4 — insert — ambiguity — mark-down from RESERVED/IN_TRANSIT/DOWN/DISPOSED → ERR_EQUIPMENT_NOT_AVAILABLE — equipment.py:99-101
- §3.4 — revise — mismatch — manual work-order create accepts kind REPAIR or PREVENTIVE (PRD was self-contradictory) — workorders.py:29-31
- §3.5 — insert — ambiguity — only PLANNED/EN_ROUTE jobs occupy the lowboy buffered diary — logic.py:323
- §3.5 — insert — ambiguity — depart with unit not IN_TRANSIT → ERR_INVALID_STATE — transport.py:103-104
- §3.5 — insert — ambiguity — direction filter accepts origin/from, destination/to, else ERR_INVALID_REQUEST — projects.py:131-140
- §3.6 — insert — ambiguity — utilization denominators of zero or negative days pin figure to 0 — logic.py:190-202
- §3.7 — revise — ambiguity — redeployment read gated on IDLE alone (SERVICE_DUE served with zero streak); non-IDLE → ERR_EQUIPMENT_NOT_AVAILABLE — equipment.py:155-167
- §3.7 — insert — ambiguity — candidate objects carry project_id, project_code, score_bp — logic.py:278-279
- §3.7 — insert — ambiguity — idle streak counts whole calendar-day boundaries since entering IDLE+SERVICE_OK; entry day counts as day 0 — logic.py:287-292
- §3.9 — revise — ambiguity — residual: depreciation rounded half-up to whole cents first, then subtracted from acquisition cost (both variants) — logic.py:246
- §3.9 — insert — ambiguity — disposal before acquisition_date counts as zero months — logic.py:226-230
- §4 table — revise — mismatch — POST /fleet/work-orders row reworded to "(kind REPAIR or PREVENTIVE; …)" — workorders.py:29-31

Everything else (state machines, allocation/own-vs-rent/utilization formulas, damage rounding and cap, transport buffered-interval rule, budget guards, OCC, error priority, envelope shape) already uniquely pinned; left untouched.
