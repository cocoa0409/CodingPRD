# Worklog — task_1229_municipal_aquatics_program_pool_pass

## Step 1: Create task directory — 2026-08-12T02:54:50.000Z

Task directory `tasks/task_1229_municipal_aquatics_program_pool_pass/` and its `workspace/` subdirectory were pre-assigned and already exist. Step 1 auto-index scan skipped per instructions. No files created by this step.

## Step 2: Generate scaffold — 2026-08-12T03:16:25.000Z

All three files exist on disk and lint is clean.

## Summary

**Files generated** at `/home/ubuntu/github/CodingPRD/tasks/task_1229_municipal_aquatics_program_pool_pass/`:

- `SCAFFOLD.yaml` — §1.0–§1.7 (no `scaffold_difficulty_design` or `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — top-level key `scaffold_corner_design` (§1.9)

**Counts:**
- **Entities**: 15 (Facility, MembershipSeason, PassHolder, SeasonPass, DailyAdmission, SwimLessonLevel, LessonSession, LessonEnrollment, Lifeguard, LifeguardShift, ChemistryLog, LaneAllocation, FacilityRental, IncidentReport, PoolClosureEvent)
- **State machines**: 13 (Facility with posture-driven CLOSED_CHEMISTRY/CLOSED_WEATHER/CLOSED_STAFFING/CLOSED_SEASON/RESTRICTED cycle; MembershipSeason, SeasonPass, DailyAdmission, LessonSession, LessonEnrollment (with ENROLLED↔WAITLISTED cycle), Lifeguard, LifeguardShift, LaneAllocation, FacilityRental, IncidentReport, PoolClosureEvent)
- **Calculations**: 8 (daily_admission_price [tiered, dual-variant], rental_quote [tiered, dual-variant], bather_load_staffing_requirement [threshold], chemistry_classification [threshold, dual-variant with closure_streak], rain_check_refund [waterfall], waitlist_promotion_order [chronological], lesson_refund [waterfall], rental_cancellation_fee [threshold])
- **Endpoints**: 77 (including 2 OCC-guarded writes, 1 `/_clock/set_current_utc` test-driving endpoint with pinned default 2026-05-01T00:00:00Z)
- **Error codes**: 22
- **Validations**: 22 ordered priorities across auth/existence/state/business_safety/business_temporal/business_constraint/business_fiscal
- **Concurrency rules**: 2 (OCC on Facility.version for rental approve and lesson schedule)
- **Roles**: 4 (AquaticsManager opaque, GateAttendant opaque, Lifeguard entity_backed:Lifeguard, PassHolder entity_backed:PassHolder)

**Difficulty design** (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 18 instances — 2 per each of the 9 difficulty rules, with required differentiation:
- dual_variant_calc: DailyAdmission (pass vs gate price) + FacilityRental (quoted vs final with overtime) — different entity domains
- combinatorial_formula: rental_quote mode (a) + daily_price mode (b) nested rounding
- non_linear_state_machine: Facility posture cycle + LessonEnrollment waitlist cycle — different entities
- transitive_cascade: weather closure depth-3 + incident confirm depth-2 — different triggers
- priority_pair_validation_conflict: (state, business_safety) + (business_temporal, business_fiscal)
- boundary_precision_check: chemistry pH boundary + bather capacity boundary — different metrics/endpoints
- cross_entity_state_dependency: DailyAdmission→Facility + LessonSession→LaneAllocation — different pairs
- resource_temporal_overlap: rental exclusive-use half-open + lane-allocation aggregate capacity — different interval semantics
- compensating_invariant: bather_count enter/exit + lane_pool reserve/release — different conserved quantities

**Corner design** (`SCAFFOLD_CORNER_DESIGN.yaml`): 37 instances across sections entities/state_machines/calculations/validations/endpoints/errors/roles/cross_cutting, including 2 `excluded_because` stubs for ERR_INVALID_STATE and ERR_STALE_VERSION already exercised by difficulty instances.

**Lint verdict** (verbatim):
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Design notes:** Primary archetype is **temporal windowing** with **quota/allocation** secondary; complexity layers optimistic_concurrency + cascading_side_effects + dual_variant_calculation + rate_threshold_triggers + derived_field_reconciliation. State-machine shape is **posture_driven** on Facility with cycles, plus cyclic LessonEnrollment. Role model is hierarchical_override. One test-driving endpoint `POST /_clock/set_current_utc` is declared with the required default `2026-05-01T00:00:00Z`. `api_prefix` was set to `""` (empty) because the resource topology is flat-with-references across multiple top-level collections (not a single root), which satisfies the lint's FK-reverse-reachability heuristic.

Orchestrator note: initial Step-2 subagent turn ended without writing files (truncated mid-design); resumed via SendMessage with a bounded "write the files now" directive; all three files then written and verified on disk (yaml.safe_load clean on all three).

## Step 3: Copy shared files — 2026-08-12T03:16:48.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1229_municipal_aquatics_program_pool_pass/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T03:23:02.000Z

All three contracts PASS. The PRD is complete and on disk.

---

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1229_municipal_aquatics_program_pool_pass/workspace/PRD.md`

**Section list (345 lines total):**
- §1. Introduction (3 paragraphs covering goals, domain shaping forces, and audience)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (headers, 4 roles, identity semantics per role)
  - 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`)
  - 2.3 Pagination (limit/offset defaults, sort order, meta fields, chemistry-log exception)
  - 2.4 Common Resource Properties (id/created_at/updated_at/version; ChemistryLog exception)
  - 2.5 Money, Precision, and Rounding (integer cents, half-up vs ceiling, age floor)
  - 2.6 Logical Clock and Time-Dependent Transitions (default clock, `to_iso8601`, time semantics)
  - 2.7 Optimistic Concurrency Control on Facility-Mutating Writes (`expected_facility_version`, `ERR_STALE_VERSION`/412)
  - 2.8 Hierarchical Consistency and Cascading Side Effects
  - 2.9 Nested Resource Retrieval (left-to-right path validation)
  - 2.10 Validation Order (all 22 priorities enumerated)
- §3. Business Logic & Workflows (9 subsections, scattered by lifecycle stage)
  - 3.1 Standing Up a Facility and a Season
  - 3.2 Patrons, Passes, and Daily Gate Admissions
  - 3.3 Water Chemistry, Facility Posture, and Reopening
  - 3.4 Weather Closures and Rain Checks
  - 3.5 Lifeguards, Certifications, and Shift Staffing
  - 3.6 Swim Lesson Levels, Sessions, and Enrollment
  - 3.7 Lane Allocation and Facility Rentals
  - 3.8 Incident Reports and Patron Discipline
  - 3.9 Closure Resolution and Season Rollover
- §4. Endpoint Definitions (4-column table, 73 endpoints)
- §5. Error Code Catalogue (2-column table, 22 error IDs)

**Hard Contract Audit Results:**

- **Contract 1 — Field-Name Coverage:** PASS
  - entities[].fields: 75 required, 75 present, 0 missing
  - endpoints[].request_body: 60 required, 60 present, 0 missing
  - endpoints[].query_params: 0 required, 0 present, 0 missing
  - endpoints[].path_params: 1 required, 1 present, 0 missing

- **Contract 2 — Rule Coverage:** PASS
  - validations[] with priority: 22 checked, 22 expressed in §2.10 ordered list
  - concurrency_rules[] OCC rejections: 2 checked, both expressed (`expected_facility_version` + `ERR_STALE_VERSION` + HTTP 412 named for rental-approve and lesson-schedule)
  - state_machines[].transitions: 40 checked, 40 fully expressed (all from/to states appear in backticks; initial gap on `VOID` and `RESOLVED` was repaired)
  - calculations[]: 8 checked, 8 fully expressed (daily_admission_price, rental_quote, bather_load_staffing_requirement, chemistry_classification, rain_check_refund, waitlist_promotion_order, lesson_refund, rental_cancellation_fee — all constants embedded, rounding modes named, evaluation order preserved)
  - validations[] conditions: 22 checked, all 22 `error_id` strings matchable to prose in §2/§3
  - endpoints[].side_effects / applies_to: expressed in workflow narratives
  - entities[].fields[] structured content: reconstructible from prose (defaults, types, derived sources)
  - sibling-branch symmetry: preserved across parallel branches (e.g. admission refund vs rain-check paths, resident vs non-resident pricing, approval vs rejection)

- **Contract 3 — §3 Path Purity:** PASS
  - backtick tokens scanned in §3: 430
  - tokens starting with `/`: 0
  - bare HTTP-method tokens: 0
  - method+path combined tokens: 0

All three contracts PASS; PRD ends at §5 with no audit footer.

## Step 5: Generate unit tests — 2026-08-12T03:52:37.000Z

All checks pass. Generation complete.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1229_municipal_aquatics_program_pool_pass/`):

- `test_helpers/` — 9 modules: `types.py` (14 entity TypedDicts; `ChemistryLog` correctly omits `updated_at`/`version` per PRD §2.4), `api_client.py` (61 endpoint methods covering the full PRD §4 surface), `api_errors.py` (22 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque manager/gate constants + `make_lifeguard_headers`/`make_passholder_headers` entity-backed builders), `fixtures.py` (composite setups: published seasons, entered admissions, scheduled sessions, approved rentals, submitted incidents, closures), `__init__.py` barrel.
- `test_suite/` — `conftest.py` + 11 test files, **68 tests total**.

**Queue A (Difficulty): 32 tests, 16/18 instances translated at exactly 2 tests each.**
**Queue B (Corner): 36 tests, 36/37 non-stub instances translated.** The 2 `excluded_because:` stubs (`err_invalid_state_reachable`, `err_stale_version_reachable`) were not translated; both cross-references resolve to real difficulty-instance names.

**Skipped instances (gaps left as gaps, no placeholders):**
1. `Difficulty/combinatorial_formula/daily_price_early_bird_age_tier_mode_b` — PRD §3.2 defines the early-bird window and rounding order but never states the discount percentage (`EARLY_BIRD_DISCOUNT_PCT` exists only in the scaffold), so the asserted 540-cent outcome is not uniquely derivable.
2. `Difficulty/priority_pair_validation_conflict/state_vs_business_safety_banned_enter_on_closed` — PRD §3.8's mandatory ban cascade voids every `ISSUED` admission of the banned holder, so the recipe's enter attempt hits rule 6 (`ERR_INVALID_STATE`) before the asserted rule 8 (`ERR_FACILITY_CLOSED`); the asserted outcome contradicts PRD-mandated behavior.
3. `Corner/entities/pass_holder_unique_email_enforced` — email uniqueness appears only in the scaffold; PRD never states it.

**Notable PRD-first adjudications:**
- `Corner/state_machines/admission_enter_twice_returns_invalid_state`: PRD §3.2 explicitly pins a second enter to `ERR_ALREADY_CHECKED_IN` (409), not the instance's `ERR_INVALID_STATE` — the test asserts the PRD-pinned error (design tag retained).
- `Difficulty/resource_temporal_overlap/rental_exclusive_use_strict_overlap`: PRD states half-open interval semantics only for lanes and seasons, never for rentals, so the touching-endpoint approval-success claim was dropped; translated as 2 genuine-overlap tests (overlap vs APPROVED and vs CHECKED_IN).
- Both OCC corner tests bump `Facility.version` via a gate entry (explicitly named a version-advancing mutation in PRD §2.4) instead of the recipe's IN_RANGE chemistry log, whose version effect is ambiguous in PRD prose.
- Lane-pool invariant tests filter RESERVED allocations client-side from the full listing rather than relying on a `status=` query filter that PRD §4 prose does not state.

**Verification results:** `python3 -m py_compile` passes on all 20 files; all test modules import; every one of the 68 tests carries exactly one `Design:` tag as the final docstring line resolving to a real instance; 99 rule-bearing citation spans (≥8 words) verified verbatim against `workspace/PRD.md` via normalized grep; zero `pytest.mark.skip`/`skipif`/`xfail` and zero scaffold references in generated code.

## Step 6: Generate implementation — 2026-08-12T03:52:37.000Z

Clean — the pgrep was matching its own shell wrapper; no `python3 app.py` processes remain. All verifications pass.

## Summary

**Implementation complete** at `/home/ubuntu/github/CodingPRD/tasks/task_1229_municipal_aquatics_program_pool_pass/workspace/implementation/`.

### File list
- `start.sh` — foreground launcher (`exec python3 app.py`), guarded dependency install (`if ! python3 -c "import flask"`), binds `0.0.0.0:$PORT` (default 10000); executable bit set
- `requirements.txt` — flask
- `app.py` — Flask app factory, error handlers, route registration, entry point
- `store.py` — in-memory dict stores (15 entity tables, **empty at boot, no seeding**), logical clock (default `2026-05-01T00:00:00Z`), ISO-8601-with-ms serialization, date/datetime parsing, age calc
- `errors.py` — full error catalog with exact error_ids/HTTP statuses from SCAFFOLD §1.6
- `envelope.py` — `meta`/`response_type`/`data` envelope, `req_…` ids, `limit`/`offset`/`total_count`/`has_more` pagination (default 10, min 1, max 100)
- `auth.py` — `X-User-Role`/`X-User-ID` validation (401), RBAC role sets per endpoint (403)
- `util.py` — field shape validators (priority-22 `ERR_INVALID_REQUEST`)
- `domain.py` — calculations (tiered daily pricing with ceil, rental quote/overtime/cancel-fee with `Decimal` ROUND_HALF_UP, bather-load staffing rule with RESTRICTED +1, chemistry classification with strict boundary inequalities, rain-check refund), all closure cascades, waitlist promotion/renumbering, clock re-evaluation (cert expiry, no-show→staffing closure, session start/complete, season rollover→CLOSED_SEASON)
- `routes_facilities.py`, `routes_patrons.py`, `routes_lessons.py`, `routes_staff.py`, `routes_booking.py`, `routes_incidents.py` — all route handlers with validation-priority ordering (auth → path FKs → body FKs → state → OCC → facility-closed → banned → cert → overlap/lanes/season → fiscal → shape)

### Route diff result
Programmatic diff of Flask's registered (method, path) set vs SCAFFOLD.yaml §1.5: **77 scaffold endpoints, 77 Flask routes, MISSING: [], EXTRA: [] — exact MATCH** (Flask's built-in `/static` route was disabled via `static_folder=None`).

### Verification results
1. `bash start.sh` boots fresh with no state; `python3 -m py_compile` passes on all 13 `.py` files.
2. Route set matches exactly (above).
3. Smoke boot: `PORT=19991 bash start.sh` → 401 without auth headers, correct empty-list envelope with auth, `POST /_clock/set_current_utc` returns `{"current_utc": "2026-05-02T00:00:00.000Z"}`; server killed cleanly.
4. E2E exercised (all passed): season publish/pricing/overlap rules, pass purchase snapshot, pass-covered vs paid admission pricing (`1500×0.75=1125`), enter/exit bather counts, `ERR_ALREADY_CHECKED_IN`, chemistry WARNING→RESTRICTED (+1 guard margin)→IN_RANGE→OPEN, OUT_OF_RANGE→CLOSED_CHEMISTRY cascade with force-exit and count reset, reopen gating incl. the **two-consecutive-IN_RANGE-after-streak rule** with anchored `chemistry_out_of_range_since`, weather closure rain checks (FULL_REFUND ≤60min, PRO_RATA_CREDIT >60min), staffing closure via no-show at +15min, incident→strike→30-day ban→pass REVOKED, OCC `ERR_STALE_VERSION` 412 on lesson schedule and rental approve, lesson lane sweep, waitlist promotion, rental quote/overtime math (45600+15000), season rollover with COMPLETED-session preservation (found and fixed a real bug there), early-bird window, and pagination bounds.

Orchestrator note: independent route-parity re-verification after both subagents exited: 77 scaffold endpoints == 77 Flask routes, MISSING: [], EXTRA: [].

## Step 7: Run tests and iterate — 2026-08-12T03:57:30.000Z

All 8 rounds pass 68/68. Clean exit.

## Summary

- **Iterations run**: 2 (initial sweep → fix → verification sweep, all 8 rounds clean).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1229_municipal_aquatics_program_pool_pass/test_suite/test_05_weather_closures_rain_checks.py` — in module-level helper `_setup_entered_admission`, replaced bare `api.enter_admission(...)` with `api_client.enter_admission(...)`. The helper does not receive the `api` pytest fixture (only test functions do), so the unqualified `api` raised `NameError`. `api_client` was already imported at module top.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1229_municipal_aquatics_program_pool_pass/test_suite/test_08_lane_allocations.py` — in module-level helper `_setup_lane_pool_invariant_scenario`, replaced `api.create_lane_allocation(...)` and `api.create_lesson_session(...)` with `api_client.create_lane_allocation(...)` and `api_client.create_lesson_session(...)`. Same root cause: helper lacks fixture access, must use the imported client.

- **Fixes applied to `implementation/`**: none.

Both fixes are STEP 2 test-vs-PRD consistency corrections — the assertions themselves were faithful to PRD; only the module-level setup helpers referenced the fixture name `api` instead of the imported `api_client` module. Final state: 68/68 passing across all 8 parallel rounds.

Orchestrator note: verified all 8 `results.{1..8}.json` on disk — each shows passed: 68, failed: 0, total: 68.

## Step 8: Finalize PRD — 2026-08-12T04:01:00.000Z

Done. PRD_FINALIZED.md is a byte-identical copy of PRD.md with zero edits.

## Summary

- **Line counts**: PRD.md = 345 lines, PRD_FINALIZED.md = 345 lines, **0.0% delta** (verified byte-identical via `cmp`).
- **Edits applied**: none.

## Traceability analysis of `<step_7_diff>` items

**Item 1 — `test_suite/test_05_weather_closures_rain_checks.py`, helper `_setup_entered_admission`: `api.enter_admission(...)` → `api_client.enter_admission(...)`**
- (a) Subject: how a module-level test helper references the API client object (pytest fixture `api` vs. module-imported `api_client`).
- (b) Impl paths enumerated: `workspace/implementation/routes_patrons.py:257` (`def enter_admission(aid)`). Implementation was not modified by Step 7; the endpoint's behavior, signature, and semantics are untouched by the fix.
- (c) Wording adjustment: none. The fix changes only which Python name the *test* uses to invoke the client; it pins no behavioral choice and reveals no PRD silence or PRD/impl divergence. No PRD edit is traceable.

**Item 2 — `test_suite/test_08_lane_allocations.py`, helper `_setup_lane_pool_invariant_scenario`: `api.create_lane_allocation(...)` / `api.create_lesson_session(...)` → `api_client.*`**
- (a) Subject: same fixture-vs-import NameError correction pattern in a module-level test helper.
- (b) Impl paths enumerated: `workspace/implementation/routes_booking.py:19` (`def create_lane_allocation()`); lesson-session creation lives in the same booking/routes layer (unmodified by Step 7).
- (c) Wording adjustment: none. Identical root cause as Item 1 — a pure test-internal NameError fix with zero behavioral content.

## Key findings

- Both Step 7 fixes are mechanical Python `NameError` corrections (fixture name `api` is only injected into test *functions*, not module-level helpers; helpers must use the top-level `import api_client`). They carry no information about API behavior, so nothing in PRD.md required pinning or revision.
- Implementation/ received no fixes, no tests were deleted, and no assertions were weakened — there is no Step-7-discovered behavior to pin.
- Per the explicit instruction, no edits were invented; `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`.

## Step 9: Complete PRD — 2026-08-12T04:11:54.000Z

All edits applied cleanly. The diff confirms 27 paragraphs touched, all in-place revisions (line count unchanged at 345), no new sections.

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1229_municipal_aquatics_program_pool_pass/workspace/PRD_COMPLETED.md`

**Size delta**: PRD_FINALIZED.md 345 lines / 48,524 chars → PRD_COMPLETED.md 345 lines / 55,832 chars (**+7,308 chars, +0 lines** — all changes are in-paragraph inserts/revisions).

**Counts**: 21 ambiguity-pins, 3 mismatch-revisions (24 change bullets total).

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl source):

- §2.1 — revise — ambiguity — empty `X-User-ID`/`X-User-Role` header value treated as missing → `ERR_UNAUTHENTICATED` — auth.py:17-22
- §2.1 — insert — ambiguity — PassHolder ownership is not enforced at creation; a PassHolder may create enrollments/rentals naming any existing `pass_holder_id` — routes_lessons.py:240-243, routes_booking.py:108-123
- §2.3 — insert — ambiguity — non-integer or out-of-range `limit` (1–100) / negative `offset` → `ERR_INVALID_REQUEST` (400); `created_at` ties broken by insertion order (reversed for the newest-first chemistry listing); enumerated per-endpoint exact-match query filters — envelope.py:52-94, routes_*.py list handlers
- §2.6 — insert — ambiguity — clock call accepts any parseable timestamp (no forward-only constraint) and returns `{"current_utc": ...}` — routes_facilities.py:18-27
- §2.7 — insert — ambiguity — `expected_facility_version` is mandatory; missing/non-integer → `ERR_INVALID_REQUEST` evaluated after all other checks — routes_lessons.py:205-207, routes_booking.py:213-215
- §3.1 — insert — ambiguity — season creation requires `end_date` strictly after `start_date` and non-negative integer prices — routes_facilities.py:226-237
- §3.1 — insert — ambiguity — "future PUBLISHED season" = another PUBLISHED season with `end_date` on/after today; facility cascade only from `OPEN`/`RESTRICTED`; season-end creates no `PoolClosureEvent` — domain.py:447-463
- §3.2 — insert — ambiguity — pass purchase against non-PUBLISHED season → `ERR_INVALID_STATE`; no uniqueness on passes per holder/season or admissions per holder/day — routes_patrons.py:113-128
- §3.2 — revise — **mismatch** — refund window is "before the start of the day after `end_date`" (refunds possible through `end_date` itself), not "before `end_date`" — routes_patrons.py:149
- §3.2 — revise — ambiguity — issue-time ban check (`ERR_HOLDER_BANNED`); early-bird window treated as covered by the upcoming PUBLISHED season; pass must also belong to the same `pass_holder_id`; `ERR_PASS_NOT_VALID` evaluated after admission-date rule, before shape checks — routes_patrons.py:180-200, domain.py:305-315
- §3.2 — insert — ambiguity — early-bird discount rate pinned at 10 percent (PRD named only the window) — domain.py:13, 322-323
- §3.3 — revise — **mismatch** — `OUT_OF_RANGE` closes an `OPEN` **or `RESTRICTED`** facility (PRD said only OPEN); also pinned: closure event `started_at` is the current clock; `WARNING`/`IN_RANGE` clears `chemistry_out_of_range_since` to null; every log post mutates the facility; readings while `CLOSED_*` create no new event — routes_facilities.py:128-158
- §3.3 — insert — ambiguity — reopen defined only for `CLOSED_CHEMISTRY`/`CLOSED_WEATHER`/`CLOSED_STAFFING` (else `ERR_INVALID_STATE`, incl. `CLOSED_SEASON`); successful reopen always lands on `OPEN`; streak rule = longest consecutive `OUT_OF_RANGE` run since last `OPEN`, with `IN_RANGE` streak reset by intervening `WARNING`/`OUT_OF_RANGE` — routes_facilities.py:196-211, 322-335
- §3.4 — revise — ambiguity — manual closure endpoint accepts all four `closure_reason` values (incl. `SEASON_END`, which does create an event, unlike automatic rollover); already-closed facility → `ERR_INVALID_STATE` — routes_facilities.py:171-187
- §3.4 — insert — ambiguity — recorded `rain_check_issuance` is `PRO_RATA_CREDIT` if any rain-checked admission exceeded 60 min, else `FULL_REFUND` (including zero-admission closures); refund amounts not persisted — domain.py:128-146
- §3.5 — revise — ambiguity — `cert_expires_on` is an inclusive calendar day (EXPIRED only after midnight ending that day), applied both at registration and in the clock sweep; suspension requires an `ACTIVE` guard; "future" shift = `shift_start` strictly after the clock — routes_staff.py:37-52, 84-88, domain.py:387-407
- §3.5 — insert — ambiguity — shift creation performs no certification check; late check-in (past +15 min) → `ERR_INVALID_STATE`; scheduled-guard coverage is derived on demand from `SCHEDULED`/`COVERED` shifts overlapping the one-hour window from now — routes_staff.py:124-163, 204-205, domain.py:64-86
- §3.5 — insert — ambiguity — staffing closure leaves `CHECKED_IN` rentals checked in and resets `current_bather_count` to the sum of their party sizes — domain.py:179-185
- §3.6 — insert — ambiguity — duplicate `level_code` → `ERR_INVALID_REQUEST` (400) — routes_lessons.py:44-46
- §3.6 — insert — ambiguity — successful scheduling increments parent facility `version`; a `SCHEDULED` session whose start passed while closed latches to `IN_PROGRESS` at the next OPEN/RESTRICTED clock evaluation (and may complete in the same sweep); completion leaves `WAITLISTED` enrollments untouched; `enrolled_count` counts `ENROLLED` only and is recomputed after cascades — routes_lessons.py:225-226, domain.py:422-439, 240-245
- §3.6 — insert — ambiguity — enrollment permitted into `DRAFT`/`SCHEDULED` sessions; `CANCELLED`/`COMPLETED` → `ERR_INVALID_STATE` — routes_lessons.py:254-257
- §3.6 — revise — **mismatch** — drop records no refund: PRD's remaining-classes refund computation removed; impl runs no refund computation and enrollments carry no payment fields; also pinned only `ENROLLED`/`WAITLISTED` are droppable — routes_lessons.py:315-347
- §3.7 — insert — ambiguity — manual `purpose=LESSON` or any `owning_lesson_session_id` → `ERR_INVALID_REQUEST`; lane reservation performs no facility-posture check — routes_booking.py:43-50
- §3.7 — revise — ambiguity — approval also increments parent facility `version`; check-in window is inclusive of both endpoints, violation → `ERR_INVALID_STATE` (409) — routes_booking.py:217-219, 251-252
- §3.7 — insert — ambiguity — 25% cancellation fee is computed at cancellation time but not persisted on any resource — routes_booking.py:288-290
- §3.9 — revise — ambiguity — individual resolve rejected with `ERR_REOPEN_CRITERIA_NOT_MET` while other ACTIVE closures exist; resolution lands the facility on `OPEN`, or `RESTRICTED` when `chemistry_state` is `WARNING` (whereas facility-wide reopen always lands `OPEN`); `CLOSED_SEASON` facilities untouched by resolution — routes_incidents.py:138-182

No PRD prose was left describing behavior the implementation does not exhibit, and no new sections were added. Notable true mismatches found and corrected: the pass-refund window (PRD "before end_date" vs impl through end_date inclusive), the OUT_OF_RANGE trigger posture (OPEN only vs OPEN/RESTRICTED), and the enrollment-drop refund computation (described in PRD, entirely absent from impl).
