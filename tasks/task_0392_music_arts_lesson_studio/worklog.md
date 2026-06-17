# Worklog — task_0392_music_arts_lesson_studio

## Step 1: Create Task Directory — 2026-06-17T00:00:00.000Z

Created `tasks/task_0392_music_arts_lesson_studio/` and `tasks/task_0392_music_arts_lesson_studio/workspace/` (index pre-assigned, not auto-computed). Verified `INSTRUCTION.md` exists at project root.

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-17T00:00:00.000Z

Generated three scaffold artifacts for **task_0392_music_arts_lesson_studio** at **Expert** difficulty. All saved under `tasks/task_0392_music_arts_lesson_studio/`:

- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Complexity profile:** primary archetype `temporal_windowing`, secondary `pricing_engine`; layers dual_variant_calculation, optimistic_concurrency, cascading_side_effects, rate_threshold_triggers; **flat** topology; **parallel** state-machine shape; **peer_roles**; immediate consistency.

**Scaffold contents:**
- **Entities:** 13 — Studio, Family, Student, Instructor, Room, Enrollment, LessonOccurrence, MakeupCredit, TuitionInvoice, Payment, RecitalEvent, RecitalRegistration, InstrumentRental (24 FKs, all with reverse-reachability GETs).
- **State machines:** 8 — Enrollment has two parallel dimensions (`lifecycle_status` PENDING_MATCH/ACTIVE/FROZEN/CANCELLED × `billing_status` UNBILLED/BILLED/PAST_DUE); LessonOccurrence is cyclic (SCHEDULED↔MAKEUP_PENDING); RecitalEvent branches (REG_OPEN→{REG_CLOSED→COMPLETED}|CANCELLED); plus RecitalRegistration, TuitionInvoice, Payment, InstrumentRental.
- **Calculations:** 9 — dual-variant tuition (provisional forward-looking vs finalized chronological, pinned rounding orders that diverge 24999 vs 25000), dual-variant practice (weighted-decay 2.60 vs raw 180), tiered family discount, plus 3 conserved-quantity/overlap helpers.
- **Validations:** 22 priority-ordered rules (auth → existence → request → referential → state → matching → temporal/overlap → makeup → fiscal).
- **Endpoints:** 61 (CRUD + action endpoints + one `/_clock/set_current_utc` test-driving endpoint + filtered-list GETs).
- **Error catalog:** 39 codes.
- **Roles:** 4 — StudioAdmin (opaque), Instructor (entity_backed:Instructor), ParentGuardian (entity_backed:Family), BillingClerk (opaque).
- **Concurrency rules:** 2 OCC rules on `Enrollment.version` (activate/resume), both 412.

**Design instance counts:**
- §1.8 Difficulty: **9 rules × 2 = 18 instances**.
- §1.9 Corner: **28 active instances + 5 `excluded_because` stubs** across all 9 claim-extraction sections.

**Verification:** `scaffold_lint.py` returns `VERDICT: clean lint`. `api_prefix` is `/studios/{studioId}` (all resources nest under the studio path). Did not look at sibling tasks.

## Step 3: Copy Shared Files — 2026-06-17T00:00:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0392_music_arts_lesson_studio/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-17T00:00:00.000Z

Generated `workspace/PRD.md` — **308 lines** — for the Music & Arts Lesson Studio API (`temporal_windowing` + `pricing_engine`).

**Sections covered:** §1 Introduction; §2 Global Specs (9 subsections: RBAC for all 4 roles, response envelope, pagination, common properties + clock, studio config constants, nested retrieval + global priority chain, OCC on Enrollment activate+resume, monetary precision + wallet invariant, cascading consistency/derived counts); §3 Business Logic (10 subsections: roster setup, enrollment matching+activation, tuition provisional vs finalized dual-variant w/ pinned rounding, family discount tiers, lesson occurrences, makeup credits, practice/progress raw vs decay-weighted dual-variant, rentals, recitals/waitlist, payments/refunds/auto-pay); §4 Endpoint table (63 endpoints, 4 cols); §5 Error catalogue (39 codes).

**Hard Contracts — all PASS:** Contract 1 (Field-Name Coverage, 88 identifiers, 0 missing); Contract 2 (Rule Coverage, both OCC rules, all transitions, both tuition calcs w/ pinned rounding, decay formula DECAY_BASE 0.95, discount tiers, freeze 3-hop cascade, cancel-credit voiding, closed-interval rental overlap, waitlist promotion, auto-pay cascade, refund reopen — 0 gaps); Contract 3 (§3 Path Purity, 0 paths/methods in §3). All 39 error IDs in §2/§3 narrative.

**Confirmation:** Did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 5: Generate Unit Tests — 2026-06-17T00:00:00.000Z

Generated test infrastructure for task_0392 (Expert band).

**Test helpers (9 files in `test_helpers/`):** `__init__.py`, `types.py` (13 entity TypedDicts + 14 enums), `api_client.py` (~60 methods), `api_errors.py` (38 errors + HTTP map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque shared headers + per-instance builders for entity-backed roles), `fixtures.py`.

**Test suite (7 files + conftest):** test_01_tuition_and_billing, test_02_practice_and_discount, test_03_enrollment_lifecycle, test_04_lesson_occurrences, test_05_recitals, test_06_resource_overlap, test_07_access_control_and_crud.

**Coverage:** 64 test functions, all collect cleanly. Queue A (Difficulty): 36 tests (all 18 difficulty instances × 2). Queue B (Corner): 28 tests (all 28 non-stub corner instances × 1). Every test carries exactly one `Design:` tag. **0 instances skipped** (5 excluded_because stubs correctly not translated).

**Key finding:** Difficulty instance `complete_occurrence_requires_active_enrollment` had `assert: ERR_INVALID_STATE` in its YAML block, but its own distinguishing_aspect/grounds and PRD §3.5 uniquely derive `ERR_ENROLLMENT_NOT_ACTIVE` (409). Tests assert the PRD-faithful `ERR_ENROLLMENT_NOT_ACTIVE`. All 42 PRD citations verified verbatim; all numeric expected values (provisional 24999, finalized 25000, weighted 2.60, autopay 24000) independently recomputed. Zero scaffold refs, zero skip/xfail.

## Step 6: Generate Implementation — 2026-06-17T00:00:00.000Z

Built Python + Flask in-memory REST API in `workspace/implementation/`.

**Source files (8 + launcher):** `start.sh` (reads `$PORT` default 10000, binds `0.0.0.0`, foreground via `exec`, guards pip install on `import flask`), `app.py`, `db.py` (in-memory store, 13 entity dicts + practice-logs aux), `helpers.py` (serialization, ISO-ms parsing, round-half-up Decimal, pagination, scoped lookups), `services.py` (calculations, derived counts, overlap, cascades), `middleware.py` (X-User-ID/X-User-Role auth), `response.py` (envelope), `errors.py` (+ requirements.txt).

**Endpoints:** 63 (all PRD §4 rows across 13 resources + clock-set, wallet-credit, state-transition actions).

**State machines:** Enrollment two independent dimensions (lifecycle_status PENDING_MATCH→ACTIVE↔FROZEN→CANCELLED; billing_status UNBILLED→BILLED↔PAST_DUE). LessonOccurrence cyclic SCHEDULED↔MAKEUP_PENDING (terminal COMPLETED/CANCELLED_LATE). RecitalEvent branching + cascade-withdraw on cancel. Cascades (freeze→cancel occurrences→mint credits→recompute discount; cancel→void credits; finalize→autopay; refund→wallet+reopen; waitlist promotion) bump version/updated_at on every touched record.

**Calculations:** Dual-variant tuition (provisional prorate-then-round vs finalized per-session-round-then-sum, Decimal ROUND_HALF_UP, integer cents). Family discount = greatest tier with min_active_enrollments ≤ active_count. Weighted progress = Σ(minutes×0.95^age_days)/60 to 2dp vs raw. Overlap: instructor recurring half-open no-buffer, room recurring buffer-expanded, dated occurrences half-open, instrument closed-interval inclusive. Makeup-credit cap + lazy expiry.

**Validation precedence:** PRD §2.6 (auth 401 → role 403 → existence 404 → body 422 → cross-studio 422 → state/business). OCC via expected_enrollment_version → ERR_STALE_VERSION (412) on activate/resume.

**Confirmed:** start.sh reads $PORT, binds 0.0.0.0, foreground; storage purely in-memory, no seeding, empty on every boot.

## Step 7: Run Tests and Iterate — 2026-06-17T00:00:00.000Z

**Iterations run:** 1 (single 8-round parallel sweep; all 8 rounds passed 64/64 on the first attempt).

**Sweep result:** All 8 concurrent per-test-server rounds reported `passed=64, total=64, failed=0, errors=0, skipped=0`. No test failed in any round, so there was no union failure set and no flakiness to chase. Results persisted at `workspace/implementation/results.1.json` … `results.8.json`.

**Tests deleted:** None.
**Fixes applied to `test_suite/`:** None.
**Fixes applied to `test_helpers/`:** None.
**Fixes applied to `implementation/`:** None.

The implementation already satisfied the full test suite deterministically across 8 concurrent rounds with no changes needed.

## Step 8: Finalize PRD — 2026-06-17T00:00:00.000Z — SKIPPED

Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). Per the skip condition, PRD.md already determined every behavior the implementation exhibits — Step 8 not spawned, no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-17T00:00:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD.md` (Step 8 skipped, so source = PRD.md).

**File metrics:** PRD.md 308 lines / 48,957 chars → PRD_COMPLETED.md 308 lines / 50,907 chars (char delta +1,950; line count unchanged — all edits in-paragraph).

**Change counts:** 8 total — 7 ambiguity-pins, 1 mismatch-revision.

- §2.4 (Common Resource Properties) — insert — ambiguity — pinned `version` initial value as 1 — db.py:54-59.
- §4 (Endpoint Definitions) — revise — mismatch — wallet-credit action returns 201 Created (not 200; clock-set still 200) — app.py:214.
- §3.3 (Tuition / finalization) — insert — ambiguity — pinned rental-surcharge attribution: ACTIVE rentals of invoice's family whose [start,end] intersects half-open [month_start, next_month) — services.py:157-173.
- §3.5 (Lesson Occurrences) — insert — ambiguity — pinned occurrence-creation error codes (ERR_ENROLLMENT_NOT_FOUND / ERR_ENROLLMENT_NOT_ACTIVE / ERR_MAKEUP_SLOT_CONFLICT) and non-cancelled colliding set {SCHEDULED, COMPLETED, MAKEUP_PENDING} — app.py:648-656, services.py:263-282.
- §3.6 (Makeup scheduling) — insert — ambiguity — pinned makeup occurrence created in SCHEDULED, scheduled_end = start+duration, instructor_id copied from enrollment, origin restored only when currently MAKEUP_PENDING — app.py:790-811.
- §3.7 (Practice / weighted score) — insert — ambiguity — pinned future-dated logged_utc (negative age) clamped to age 0 (full weight) — services.py:189-192.
- §3.9 (Recital registration) — insert — ambiguity — pinned WAITLISTED/WITHDRAWN registrations carry performance_order 0, set only while CONFIRMED — app.py:1215, services.py:313-322.
- §3.10 (Payments) — insert — ambiguity — pinned target invoice must be FINALIZED else ERR_INVALID_STATE (409) — app.py:1029-1030.

All referenced error IDs already in §5 catalogue; no new sections/paragraphs/invented behavior. One borderline divergence deliberately left unpinned (§4 generic studio_id list-filter — no observable behavioral divergence within a studio, not test-exercised).

---

## PIPELINE COMPLETE

All 9 steps executed. Final state: **64/64 tests pass across all 8 parallel per-test-server rounds.** Deliverables present: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design indices), workspace/PRD.md, workspace/PRD_COMPLETED.md, test_helpers/, test_suite/ (7 files, 64 tests), workspace/implementation/ (Flask, in-memory), results.1-8.json (all passing).
