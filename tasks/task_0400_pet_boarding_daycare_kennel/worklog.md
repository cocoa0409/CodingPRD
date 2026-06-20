# Worklog — task_0400_pet_boarding_daycare_kennel

Scenario: Pet Boarding & Daycare Facility (Kennel): reservation & run/suite assignment, vaccination requirement, daycare vs overnight & feeding/meds, capacity & temperament grouping, add-on (bath/playtime), belongings & incident log, deposit/cancellation, recurring package

Difficulty: Expert (applied only at Step 2 scaffold generation per §0.4 Expert tier: 10–15 entities / 20–32 endpoints / 18–30 validations / 3+ calculations / 4+ state machines).

## Step 1: Create task directory — 2026-06-18T00:00:00.000Z

Created ./tasks/task_0400_pet_boarding_daycare_kennel/ and ./tasks/task_0400_pet_boarding_daycare_kennel/workspace/ via mkdir -p. Target dir was pre-allocated; no auto-increment scan performed (5 parallel tasks run concurrently — auto-increment would cause ID contention).

## Step 2: Generate scaffold (Expert tier) — 2026-06-18T00:00:00.000Z

All three scaffold files are written and the lint passes clean. Here is the summary for the worklog.

## Summary — task_0400_pet_boarding_daycare_kennel

**Domain:** Pet Boarding & Daycare Facility (Kennel). Archetype: quota/allocation (finite run/suite pool) + temporal-windowing secondary; flat topology; branching state-machine shape; peer roles; immediate consistency.

**Difficulty tier: Expert** — all bands hit:
- **Entities: 10** (Facility, Owner, Pet, VaccinationRecord, Run, Reservation, RunAssignment, AddOn, Package, PackageRedemption; feeding/meds `care_plan` and belongings/incidents carried as embedded arrays on Reservation) — within 10–15.
- **Endpoints: 32** (19 POST + 13 GET) — at the 20–32 ceiling.
- **Validations: 24** (priority-ordered) — within 18–30.
- **Calculations: 4** (deposit_amount dual-variant tiered, cancellation_refund dual-variant threshold, reservation_total pinned-order aggregation, group_compatibility_score dual-variant weighted) — meets 3+.
- **State machines: 5** (Reservation branching w/ CANCELLED+NO_SHOW forks, RunAssignment cascade-driven, AddOn, Package cyclic ACTIVE↔EXPIRED, Pet parallel vaccination×temperament dimensions) — meets 4+.
- Errors: 24; Roles: 3 (FacilityManager opaque, FacilityStaff opaque, Owner entity_backed); Concurrency: 1 OCC rule on Reservation.version (assignment create, 412).

**§1.8 difficulty design:** 18 instances (9 rules × 2), each grounded in §1.1–§1.7 with executable `setup_api_calls` chains and precomputed literal asserts (deposits 3600/4320/450, refunds 4320/648/450/225/0, totals 16625/29250/0, group scores 5/2/15/0). All §0.5 differentiation clauses satisfied — notably Rule 8 uses two *different* resource entities (Run half-open suite overlap vs Pet closed-interval double-booking, added as ERR_PET_DOUBLE_BOOKED).

**§1.9 corner design:** 40 instances (30 active + 10 `excluded_because` stubs) across entities/state-machines/calculations/validations/endpoints/errors/rbac/cross-cutting/consistency sections.

**Validation results:**
- `scaffold_lint.py .` → **VERDICT: clean lint** (32 endpoints, 10 entities, 18 §1.8 + 30 §1.9 instances, 363 calls; all calls conform to §1.5, all FKs reverse-reachable).
- File-split correct (no design keys in SCAFFOLD.yaml; each design file has its single top-level key).
- All grounds references resolve; all `excluded_because` refs resolve to named §1.8 instances; 58 instance names unique across both files; enum closure clean; every error referenced; all endpoint roles declared.

**All three files written** (verified by orchestrator: SCAFFOLD.yaml 1119 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1006 lines, SCAFFOLD_CORNER_DESIGN.yaml 1136 lines).

Note: To satisfy both the 10–15 entity floor and the hard 20–32 endpoint ceiling simultaneously, the surface was kept flat (`api_prefix: ""`) with feeding/meds and belongings/incidents modeled as embedded Reservation arrays rather than separate entities, and lifecycle actions kept lean — difficulty concentrated in coupling (dual-variant calcs, depth-3 cascades on two different triggers, cross-entity gates, two-entity temporal overlaps) per §0.4 guidance.

## Step 3: Copy INSTRUCTION.md — 2026-06-18T00:00:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (bash, no subagent).

## Step 4: Generate PRD — 2026-06-18T00:00:00.000Z

The PRD is complete and all hard contracts pass. Here is the final summary.

**File written:** `workspace/PRD.md` (254 lines).

**Sections covered:**
- **§1 Introduction** — 3 paragraphs framing the quota-allocation + temporal-windowing domain and the facility business clock.
- **§2 Global Specifications** (8 subsections): 2.1 RBAC (all 3 roles with opaque vs. entity-backed `identity` prose), 2.2 fixed response envelope (verbatim, exact match confirmed), 2.3 Pagination, 2.4 Common properties + business clock (VaccinationRecord/PackageRedemption flagged as id+created_at only), 2.5 Hierarchical cascades + left-to-right path validation, 2.6 OCC on assignment create, 2.7 Precision/rounding, 2.8 Capacity/overlap/grouping discipline.
- **§3 Business Logic** (10 subsections): facilities/runs/clock, owners/pets, vaccinations, temperament review, reservation building (care plan, belongings, deposit estimate, add-ons), run assignment + confirm (eligibility, double-booking, suite overlap, daycare capacity, group-compatibility scoring, ordered confirm preconditions), packages/renewal cycle, check-in/out/close/final-bill (deposit final variant, cancellation refund tiers, no-show), incident logging, and validation ordering.
- **§4 Endpoint Definitions** — 4-column table (32 endpoints), with 201/200 status-code rules.
- **§5 Error Code Catalogue** — 2-column table (24 errors).

**Hard Contracts — all PASS:**
- **Contract 1 (Field-Name Coverage):** 68 required identifiers, 68 present, 0 missing.
- **Contract 2 (Rule Coverage):** all 5 state machines and branching transitions expressed; OCC rule (`expected_reservation_version` → `ERR_STALE_VERSION` HTTP 412 on assignment create) stated; all 4 calculations translated with constants embedded; all 24 error IDs surfaced; confirm-precondition ordering and validation precedence stated.
- **Contract 3 (§3 Path Purity):** 461 backtick tokens scanned, 0 slash-prefixed, 0 bare HTTP methods, 0 method+path combos.

§2.2 matches the fixed block byte-for-byte. All 50 state/enum values and all 3 role names present. Neither withheld design file was opened.

## Step 5: Generate unit tests — 2026-06-18T00:00:00.000Z

Generated complete test infrastructure for **task_0400_pet_boarding_daycare_kennel** from the two design indices only (no freelance walking of SCAFFOLD.yaml).

**test_helpers/** (Stage 1, 9 files, all written): `types.py` (entity TypedDicts with `common_fields:false` correctly omitting `updated_at`/`version` for VaccinationRecord & PackageRedemption), `api_client.py` (one method per §4 endpoint, subclassing `GenericApiClient`), `api_errors.py` (all 24 error IDs + HTTP-status map registered with framework), `assertions.py`, `factories.py` (input-only fields), `constants.py` (deposit/refund/total/grouping tables), `test_users.py` (opaque FacilityManager/FacilityStaff + entity-backed Owner via `make_owner_headers`), `fixtures.py` (6 composite tiers for the multi-step confirm/cancel/package/clock chains), `__init__.py` barrel export.

**test_suite/** (Stage 2): **conftest.py + 11 test files, 66 tests total.**
- **Queue A (Difficulty): 36 tests** — all 18 instances covered with ≥2 tests each (verified, zero shortfalls).
- **Queue B (Corner): 30 tests** — all 30 non-stub instances covered with ≥1 test each; every emitted Corner tag resolves to a real active instance (no orphans).

**Instances skipped:** 10 — all are `excluded_because` stubs in the corner index (NOT translated by contract); every stub's `difficulty_instance` cross-reference was verified to resolve to a real §1.8 instance that owns the assertion. Categories: errors family (5: run_overlap, run_capacity, package_not_redeemable, vaccination_required, pet_double_booked), state_machines (1: confirm_cascade_assignment_occupied), calculations (1: group_score_lenient), validations (1: checkin_too_early), cross_cutting_complexity_layers (2: occ_version_increments, wallet_credit_reconciles). No instances were skipped for PRD-coverage failure — the PRD covers every active instance verbatim.

**Verification passed:** all 18 modules byte-compile; every `api`/`api_client` method call and every `from test_helpers import` name resolves; each test has exactly one `Design:` tag (66 fns = 66 tags); no `skip`/`xfail`/`skipif` markers; all 102 PRD citations are verbatim substrings of PRD.md.

## Step 6: Generate implementation — 2026-06-18T00:00:00.000Z

Generated a complete Python + Flask implementation of the Pet Boarding, Daycare & Kennel API in `workspace/implementation/`.

**Source files:** 19 Python modules + `start.sh` + `requirements.txt` (21 files total)
- `app.py` (entry point, blueprint registration, error handlers), `db.py` (in-memory store), `errors.py`, `response.py` (envelope), `middleware.py` (auth/RBAC)
- `routes/`: facilities, owners, pets, runs, reservations, packages (6 modules)
- `services/`: calc, assignment, clock, pet, package, serialize, query, common (8 modules)

**Endpoints:** 32 Flask routes registered, covering all 33 PRD endpoint-table rows (the `check_out` route serves both the CHECKED_IN→CHECKED_OUT and the CHECKED_OUT→CLOSED transitions through one path, per the PRD design).

**Storage:** In-memory only — plain Python dicts keyed by UUID in a `DB` class. No SQLite, no file/JSON persistence, no `/tmp` cache. State is freshly empty on every process boot; `start.sh` re-invocation wipes all state. No entities are seeded, preloaded, or hardcoded at startup.

**Key behaviors:** response envelope (`meta`/`response_type`/`data`), pagination in `meta`, ISO-8601 ms timestamps, `req_`-prefixed IDs, auth headers + 3 roles + validation precedence, full reservation lifecycle with cascades, Decimal+round-half-up calculations (deposit/refund/total/grouping), OCC on `expected_reservation_version` (ERR_STALE_VERSION 412), all 24 error IDs.

**Launcher:** `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on a cheap `import flask` check, and `exec`s the server in the foreground. Confirmed clean boot and state wipe across restarts.

Orchestrator verified on disk: test_helpers/ (9 files), test_suite/ (conftest + 11 test files, 66 test functions), workspace/implementation/ (app.py, db.py, errors.py, middleware.py, response.py, requirements.txt, routes/, services/, start.sh present).

## Step 7: Test & iterate to green — 2026-06-18T00:00:00.000Z

All 8 parallel rounds pass 65/65. The clean sweep confirms the fix. Exiting with the summary.

**Iterations run:** 2 (initial sweep → diagnose+fix → confirming sweep).

**Initial state:** 65/66 in all 8 rounds — a single deterministic failure: `test_stale_reservation_version_rejected_on_second_assignment` (in `test_07_overlap_capacity_grouping.py`), failing with `AssertionError: Expected error_id 'ERR_STALE_VERSION', got 'ERR_PET_DOUBLE_BOOKED'`.

**Tests deleted (1):**
- `test_stale_reservation_version_rejected_on_second_assignment` in `test_suite/test_07_overlap_capacity_grouping.py` — **ERROR PRECEDENCE SILENCE** (STEP 1b unique-derivability collapse). The test creates a second `RunAssignment` on the same reservation/pet/window with a stale `expected_reservation_version`, expecting `ERR_STALE_VERSION` to fire before `ERR_PET_DOUBLE_BOOKED`. The PRD does not uniquely determine this ordering:
  - §2.6 and §2.4 describe the OCC mechanism but pin no precedence.
  - §3.10 states the OCC check "is the **fiscal-tier guard**" and that "the domain-specific checks described in the workflow sections above apply in the orders given there." In §3.10's own tier vocabulary, the fiscal tier runs **after** the business/temporal tier, so a faithful PRD-only reader is led to place the §3.6 temporal check `ERR_PET_DOUBLE_BOOKED` **before** the OCC fiscal-tier guard — exactly what the implementation does.
  - Two divergent PRD-faithful implementations exist: (A) "fiscal-tier guard" runs after the §3.6 temporal checks → `ERR_PET_DOUBLE_BOOKED` fires (impl, test fails); (B) OCC read as a short-circuit precondition → `ERR_STALE_VERSION` fires (test passes). The literal "fiscal-tier guard" phrasing favors (A).
  - This is not a fixable test-helper bug: any second assignment on a single reservation necessarily targets the same pet and the same derived window, so it must structurally trip pet self-exclusion under any ordering that runs the §3.6 temporal checks before the fiscal-tier OCC guard.
  - Scaffold rule that drove the test's generation: validation-rule `priority: 24, category: business_fiscal, ERR_STALE_VERSION` (scaffold-only ordering placing OCC last, plus corner `error_stale_version_trigger`).

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None. The implementation's check ordering (eligibility → pet-double-booked → suite-overlap/daycare-capacity → grouping → OCC stale-version last) traces faithfully to §3.10's "fiscal-tier guard" language and the §3.6 workflow order; no implementation check was weakened or reordered.

**Final state:** Clean 8-round parallel sweep — all 8 rounds pass 65/65 (orchestrator independently verified all 8 results.{1..8}.json: passed=65 total=65).

## Step 8: Finalize PRD — 2026-06-18T00:00:00.000Z

The single edit is applied cleanly. The line count is unchanged (the edit was within an existing paragraph on line 186). The work is complete.

**Line counts:** PRD.md = 254 lines, PRD_FINALIZED.md = 254 lines. Delta = 0 lines (+0%). The single edit extended an existing sentence within §3.10's paragraph (line 186); no lines added/removed.

**Changes (1 edit):**
- §3.10 (Validation Ordering Across Endpoints) — *revise* — pinned that the OCC `ERR_STALE_VERSION` fiscal-tier guard on the assignment-create endpoint runs **last**, after the §3.6 domain checks (eligibility → pet-double-booked → suite-overlap/daycare-capacity/grouping), so that when a stale create would also trip a domain check, the domain check (e.g. `ERR_PET_DOUBLE_BOOKED`) fires first — `routes/reservations.py:529-541` (pet-double-booked at L530, suite/capacity/grouping L533-537, OCC stale-version L540-541 last).

**Why this is the only edit:** The step_7_diff records exactly one change — deletion of `test_stale_reservation_version_rejected_on_second_assignment`, which had expected `ERR_STALE_VERSION` to precede `ERR_PET_DOUBLE_BOOKED`. No implementation or test-helper fixes were applied. The PRD's §3.10 called OCC "the fiscal-tier guard" but never pinned its position relative to the §3.6 domain checks — a genuine PRD silence over precedence. The implementation resolves it by placing OCC last.

**Per-edit pre-edit search log:**
- (a) Subject: Position of the OCC `ERR_STALE_VERSION` check in the assignment-create endpoint's validation sequence, and its relation to the §3.6 domain checks.
- (b) Impl paths enumerated/read: `routes/reservations.py:500-555` (`create_assignment`, full order confirmed: require_fields → version type → cross-facility L513-515 → state REQUESTED L520-521 → eligibility L524 → pet-double-booked L530 → suite-overlap/daycare-capacity/grouping L533-537 → OCC stale-version LAST L540-541); `errors.py:87,135`; `services/assignment.py` (domain-check helpers, none touch OCC/version); `grep err_stale_version` (raised only at reservations.py:541; only endpoint taking a version field); `grep err_invalid_state/err_cross_facility` (verified cross-facility+state run before §3.6 domain checks).
- (c) Wording adjustment: Scoped "runs last" to "after the §3.6 domain checks in their workflow order" rather than unqualified "last overall," keeping consistency with cross-facility/state checks the impl runs earlier at this endpoint.

## Step 9: Complete PRD — 2026-06-18T00:00:00.000Z

All 7 diff hunks are intentional and in-paragraph. The PRD_COMPLETED.md is complete. Here is the summary.

**File line/char counts:**
- Source `PRD_FINALIZED.md`: 254 lines, 43,623 chars
- `PRD_COMPLETED.md`: 254 lines (unchanged — all edits in-paragraph), 46,784 chars
- Char delta: **+3,161**

**Change counts:** 7 in-paragraph edits → **6 ambiguity-pins, 1 mismatch-revision**.

**Per-change bullets:**
- §2.3 (Pagination) — insert — ambiguity — non-integer/out-of-range `limit` or negative `offset` rejected with `ERR_INVALID_REQUEST` rather than clamped — `services/query.py:28-39`
- §2.3 (Pagination/listing) — insert — ambiguity — (a) sort tie-break is insertion order, (b) `GET /reservations` implicitly narrowed to caller's own `owner_id` for Owner role before filters, (c) exact per-list query-parameter filter set with unrecognized params ignored — `routes/reservations.py:178-194`, `routes/owners.py:64-71`, `routes/runs.py:70-76`, `routes/packages.py:76-79,113-117`, `services/query.py:43-47`
- §3.3 (Vaccination) — insert — ambiguity — species-required vaccine sets (DOG: RABIES/DHPP/BORDETELLA; CAT: RABIES/FVRCP), non-required vaccines stored but ignored, EXPIRED-vs-MISSING discrimination (lapsed record → EXPIRED; no record → MISSING) — `services/pet.py:10-13,39-70`
- §3.5 (Reservation create) — revise — mismatch — body FKs `pet_id`/`package_id` not existing at all yield `ERR_CROSS_FACILITY_REFERENCE` (not `ERR_NOT_FOUND`), pet before package, pet existence/facility before Owner-ownership comparison — `routes/reservations.py:73-85`
- §3.5 (Pay deposit) — insert — ambiguity — `cash_cents` must be non-negative integer (else `ERR_INVALID_REQUEST`), `pay_deposit` only from `REQUESTED` (else `ERR_INVALID_STATE`), remaining-deposit formula floored at 0 — `routes/reservations.py:210-221`
- §3.6 (Assignment create, para 1) — insert — ambiguity — `expected_reservation_version` must be integer (else `ERR_INVALID_REQUEST`); assignment createable only while reservation is `REQUESTED` (else `ERR_INVALID_STATE`), after in-facility but before eligibility — `routes/reservations.py:509-521`
- §3.6 (Assignment create, para 2) — insert — ambiguity — `run_id` not existing at all yields `ERR_CROSS_FACILITY_REFERENCE` (not `ERR_NOT_FOUND`), evaluated before state/eligibility — `routes/reservations.py:513-515`

**Notes / deliberately not pinned:** unknown-route/405 → `ERR_NOT_FOUND`, unexpected-exception → generic 500 `ERR_INTERNAL` (`app.py:34-50`) left untouched (no §5 catalogue bearing). Facility version bump on clock advance, confirm's deposit re-latch, no-show add-on cancellation, refund lead-time boundaries verified already uniquely pinned. Tests used only as auxiliary cross-reference; no assertion treated as authority.

---

## PIPELINE COMPLETE — 2026-06-18T00:00:00.000Z

Final task directory contents verified by orchestrator:
- SCAFFOLD.yaml (1119 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1006 lines), SCAFFOLD_CORNER_DESIGN.yaml (1136 lines)
- workspace/PRD.md (254 lines) → PRD_FINALIZED.md (254 lines, Step 8) → PRD_COMPLETED.md (254 lines, Step 9)
- workspace/implementation/ (Flask, 32 endpoints, in-memory) — final 8-round stability sweep all green (65/65 × 8)
- test_helpers/ (9 files) + test_suite/ (conftest + 11 files, 65 live tests after 1 Step-7 deletion)
- Difficulty: Expert tier (10 entities / 32 endpoints / 24 validations / 4 calculations / 5 state machines).
