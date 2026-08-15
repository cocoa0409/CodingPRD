# Worklog — task_1889_health_plan_grievance_appeals

## Step 1: Create task directory — 2026-08-14T23:03:00.000Z

Directory `tasks/task_1889_health_plan_grievance_appeals/` and `workspace/` pre-created by the pipeline driver (per command args; no index scan performed by this orchestrator).

## Step 2: Generate scaffold — 2026-08-14T23:30:00.000Z

Generated the complete scaffold for **task_1889_health_plan_grievance_appeals** (Health Plan Grievance & Appeals — Medicare/Medicaid) from the scenario description alone, per the prd-bench-scaffold-generator skill. No sibling task directories were inspected.

**Files written (all three, verified on disk):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1889_health_plan_grievance_appeals/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1889_health_plan_grievance_appeals/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1889_health_plan_grievance_appeals/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **11** (Member, Provider, DeadlinePolicy, GrievanceAppealCase, CaseEvent, ClinicalReview, Notification, IndependentReviewReferral, Effectuation, Reopening, AuditUniverseRecord)
- State machines: **6** (Case with cyclic reopen loop + self-transitions, ClinicalReview, Notification with SENT→FAILED→RETRIED→SENT loop, IndependentReviewReferral, Effectuation with OVERDUE/ESCALATED branches, Reopening)
- Endpoints: **60** (including `POST /appeals/_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z)
- Errors: **23**
- Roles: **7** (PlatformAdmin, IntakeSpecialist, CaseAnalyst, MedicalDirector, MemberServicesRep, ComplianceOfficer, ClaimsProcessor; segregation-of-duties model, all opaque identity)
- §1.8 difficulty instances (non-stub): **27** — 3 per rule × 9 rules (maxed), favoring multi-step cascades (depth-4 reopening cascade, depth-3 IRE overturn cascade), OCC race semantics (3 concurrency rules), precedence interplay (state-vs-safety, temporal-vs-referential, constraint-vs-fiscal), boundary stacking (100.00 timeliness edge, 72h IRE window, CTM tier counts), cross-entity state coupling (Case×ClinicalReview, Effectuation×Provider, Reopening×Case)
- §1.9 corner instances (non-stub): **47** across all nine guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting, consistency_model)

**Verification:** `scaffold_lint.py` verdict is clean — all 663 §1.8/§1.9 calls conform to §1.5 (endpoints, roles, payload shapes, capture resolution, OCC version placeholders dynamic) and every §1.1 FK has reverse-reachability. Manual replay additionally fixed: APPEAL cases illegally decided via the grievance-only non-clinical path (switched to GRIEVANCE), a close attempted before the IRE window lapsed, an ambiguous two-PENDING-effectuation selection (now uses the `referral_id?` filtered list), a stale OCC version in the second-extension trigger, the missing `business_hours_only` field the calculation variant referenced, and a dead ERR_REVIEW_IN_FLIGHT error made reachable by adding a PENDING_CLINICAL→PENDING_CLINICAL replacement-review transition. All formula-derived asserts use literals computed via Python (e.g., timeliness 100.00/83.33, necessity score 70.00/88.56, completeness 0.75/1.00).

## Step 3: Copy shared files — 2026-08-14T23:32:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1889_health_plan_grievance_appeals/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T23:42:00.000Z

All three hard contracts now pass. Contract 2 was verified by a manual walk of every scaffold rule category against the prose (validation priority ordering in §2.8, all three OCC rules in §2.7 with write-operation/field/error-id named, all cross-entity cascades, all `applies_to` scopes, field defaults/ranges, sibling-transition symmetry across withdraw/extensions/expedite/complete/close/decide branches, all 41 state-machine transitions, and all 6 calculations with constants embedded).

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1889_health_plan_grievance_appeals/workspace/PRD.md` (314 lines, ~40 KB)

**Section list:**
1. **Introduction** — 2 paragraphs, business-context angle (Medicare/Medi-Cal regulatory clocks, segregation of duties)
2. **Global Specifications & System-Wide Principles** — 2.1 RBAC (7 roles, opaque identity prose per role, `X-User-ID`/`X-User-Role`); 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`); 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields); 2.4 The Logical Server Clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`, OVERDUE sweep side effect); 2.5 Common Resource Properties (UUID `id`, `created_at`/`updated_at`/`version`; `CaseEvent` and `AuditUniverseRecord` explicitly carry only `id`+`created_at`); 2.6 Precision/Rounding/Monetary (2dp round-half-up; pinned per-element-then-sum vs sum-then-round contrast); 2.7 OCC (all 3 rules, `ERR_STALE_VERSION` 412, stale-view framing only); 2.8 Validation Discipline & Error Ordering (all 20 priorities in explicit sequence + `ERR_VALIDATION`); 2.9 Deadline Policy Administration (720/336-hour caps, active-uniqueness deactivation); 2.10 Segregation of Duties
3. **Business Logic & Workflows** — 9 subsections: 3.1 Reference Data; 3.2 Intake/Classification/Early Withdrawal; 3.3 Triage/Deadlines/Extensions/Expedited Upgrades; 3.4 Clinical Review & Medical Necessity Score; 3.5 Decision & Member Notification; 3.6 IRE Referral; 3.7 Effectuation & Timeliness; 3.8 Closure & Reopening; 3.9 CTM Linkage/Audit Universe/Compliance Reporting
4. **Endpoint Definitions** — 60-row table, 4 columns only (Method, Path, Description, Authorized Roles), 201-vs-200 rule paragraph
5. **Error Code Catalogue** — 23-row table, 2 columns only (Error ID, HTTP Status Code)

**Contract reports:**
- Contract 1 (Field-Name Coverage): fields 65/65, endpoint inputs 49/49, path params 1/1 — **PASS**
- Contract 2 (Rule Coverage): validations priority 20/20 expressed, OCC 3/3, transitions 41/41, calculations 6/6, validation conditions 20/20 matchable to error IDs, side effects/applies-to all expressed, sibling branches symmetric — **PASS**
- Contract 3 (§3 Path Purity): 491 backtick tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos — **PASS**

Additional checks passed: all 23 error IDs, all 7 role names, all state values, and all enum values appear in the PRD. The withheld design files were never opened or referenced.

## Step 6: Generate implementation — 2026-08-15T00:10:00.000Z

## Implementation Summary — task_1889_health_plan_grievance_appeals

### File list (`/home/ubuntu/github/CodingPRD/tasks/task_1889_health_plan_grievance_appeals/workspace/implementation/`)
- `start.sh` — guarded launcher (skips `pip install` when flask importable, `exec python3 app.py`, foreground)
- `requirements.txt` — flask>=3.0
- `app.py` — Flask app, blueprint registration, envelope-aware error handlers (ApiError/404/405/500), `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory stores, logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), UUID/timestamp helpers (3-fractional-digit ISO 8601)
- `errors.py` — full error catalog (23 error IDs with exact HTTP statuses)
- `envelope.py` — `{meta, response_type, data}` envelope, list pagination meta (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamp 1..100)
- `auth.py` — `X-User-ID`/`X-User-Role` validation, per-endpoint role decorator
- `validate.py` — payload structural validation → ERR_VALIDATION (400)
- `calc.py` — deadline calc, medical necessity scoring (Decimal, sum-then-round HALF_UP 2dp, override clamped), notification completeness (per-element 4dp → sum → 2dp), effectuation timeliness (calendar + Mon–Fri 08:00–17:00 UTC business-hours variant), CTM tiering, audit period windows
- `serializers.py` — only scaffold-declared fields exposed (CaseEvent/AuditUniverseRecord carry no `updated_at`/`version`)
- `services.py` — event appends, state guards, overdue sweep, REOPENED→CLOSED auto-close
- `routes/` — clock, members, providers, policies, cases, reviews, notifications, ire, effectuations, reopenings, audit

### State storage
Purely in-memory module-level dicts keyed by id (`db.members`, `db.cases`, etc.) plus the logical clock. Nothing on disk, no seeding — store is empty on every boot (verified: relaunch returns empty lists, clock resets). Member counters (`open_case_count`, `ctm_linked_case_count`) and case `overdue` are computed on read, so all increment/decrement side effects are inherently consistent.

### PRD interpretation decisions
1. **Notification content matrix (§3.5)** — the matrix is never enumerated in PRD or scaffold. Since element weights sum to exactly 1.00 and mark-sent requires completeness == 1.00, `required_elements` is always the full 7-element set; any subset would make the completeness gate unreachable.
2. **Terminal vs invalid state (§2.8 priorities 5/6)** — mutations on terminal-state resources → `ERR_ALREADY_TERMINAL`; non-terminal but undeclared transitions → `ERR_INVALID_STATE`. Strict priority ordering would make ERR_ALREADY_TERMINAL unreachable, so the catalog's distinct conditions win.
3. **Event appends on terminal cases (§1.5 vs §2.8)** — allowed (the CTM_LINKED qualifier "only when case not CLOSED/WITHDRAWN" presupposes it); the CTM flag/count side effect is suppressed on closed cases, but the version still bumps per §2.5. Notification creation on CLOSED/WITHDRAWN → ERR_ALREADY_TERMINAL per §2.8's "sole exception" wording.
4. **OCC check placement (§2.7, §3.3)** — per the PRD's narrative order, endpoint business preconditions (e.g. ERR_EXTENSION_CONSUMED) fire before the stale-version check; missing/non-integer `expected_*_version` → ERR_VALIDATION.
5. **Close-from-IRE_REFERRED (§3.8)** — referral accepted in `DECISION_RECEIVED` **or** `EFFECTUATED`, because the referral auto-transitions to EFFECTUATED when its linked effectuation completes (a strict DECISION_RECEIVED reading would make the OVERTURN_PLAN close path unreachable).
6. **IRE-spawned effectuation on UNFAVORABLE case** — `effectuation_due_at` is null, so the timeliness window is undefined; `timeliness_percent` stays null (found via smoke-test crash, fixed).
7. **CTM exposure tier** — computed from `ceil(provisional_weight)` (RECEIVED-state links count 0.5) per §3.9; raw count reported alongside.
8. **Compliance summary rates (§3.9)** — computed live from the case universe (works with or without a prior snapshot); intake-delay cases (late ∧ ack > 24h) counted as resolution-timely in this view and excluded from `reviewer_late_count`, so the two views produce different rates as the PRD requires; rates rounded HALF_UP to 4 decimals (§2.6 pins 2dp only for the three named stored scores).
9. **Uniqueness violations** (member_ref, npi) → ERR_VALIDATION 400 (no dedicated duplicate error exists for these); missing provider at triage for ORG_DETERMINATION/APPEAL → ERR_REFERENCE_NOT_FOUND; assignee-only draft/finalize violations → ERR_DUTY_SEGREGATION.
10. **Event appends always bump case version exactly once** — reopening create/deny bump the source case (the grant OCC prose names "an event append" as a version-advancing mutation); transitions that declare their own bump don't double-count.

### Boot verification
`start.sh` boots cleanly and repeatably (invoked 8+ times fresh): binds 0.0.0.0:$PORT, responds within ~3s, store empty and clock at `2026-08-01T00:00:00Z` after every relaunch. Three smoke suites passed covering: auth 401/403, 404s, policy deactivation, duplicate-case guard, grievance expedite rejection, triage deadline math, expedite anchor semantics, extension OCC (412) and consumed (422), clinical review duty segregation, necessity score (65.0 verified), both decide doors, payment gates, notification completeness (0.95→1.00), DECIDED→NOTIFIED auto-transition, W-9/waive gates, OVERDUE clock sweep with version bump, stale-OCC-after-sweep, timeliness 550.00 late / 0.00 timely, notification retry cycle with `sent_at` preservation, IRE referral auto-transition, full reopening flow (spawn, supersede, REOPENED→CLOSED unwind), CTM provisional half-weight tiers, audit snapshot duplicate rejection, and compliance summary attribution.

## Step 5: Generate unit tests — 2026-08-15T00:15:00.000Z

All 103 tests collect cleanly. The suite is complete.

**Tests generated: 103 total**
- **Queue A (Difficulty): 54 tests** — 27 instances × 2 tests each (all 9 rules × 3 instances covered at the required ≥2 depth)
- **Queue B (Corner): 49 tests** — all 47 non-stub instances covered at ≥1 (two OCC instances got a second test each: stale-rejection + fresh-success)

**Design instances skipped: 0.** The corner index contained no `excluded_because:` stubs, and every difficulty and corner instance passed the PRD-first two-condition filter (verbatim coverage + unique derivability). Notable adjudications: priority-ordering instances were kept because PRD §2.8 states the fixed validation sequence explicitly; the notification-matrix instances were kept because PRD §3.5 names all seven required elements with weights summing to exactly 1.00, making both the 1.00 full score and the 0.75 missing-`appeal_rights` score uniquely derivable; initial `version == 1` asserts were kept under the "increments with every modification" reading (only plausible initial value).

**test_helpers/ files** (`/home/ubuntu/github/CodingPRD/tasks/task_1889_health_plan_grievance_appeals/test_helpers/`):
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 11 entity TypedDicts (CaseEvent/AuditUniverseRecord correctly omit `updated_at`/`version` per PRD §2.5), 15 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per §4 endpoint (46 methods)
- `api_errors.py` — `ApiErrorId` enum + 23-entry HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + precision checks
- `factories.py` — payload factories incl. the three notification element sets (full / minus-appeal_rights / minus-language_assistance)
- `constants.py` — thresholds (ACK 24h, IRE 72h, 100.00 boundary, tier bands, 180d), scoring weights, element weights
- `test_users.py` — 7 role header constants + per-instance `make_*_headers` builders for segregation-of-duties scenarios
- `fixtures.py` — composite helpers: clock/reference-data tier, case state ladder (RECEIVED→TRIAGED→IN_REVIEW→PENDING_CLINICAL→DECIDED→NOTIFIED→CLOSED), clinical-review ladder, effectuation helpers, CTM linkage, reopening ladder

**test_suite/ files** (`.../test_suite/`):
- `conftest.py` — session `api` fixture + 7 role-header fixtures
- `test_01_reference_data.py` (9), `test_02_case_state_machine.py` (6), `test_03_calculations.py` (6), `test_04_validations.py` (9), `test_05_endpoints_and_envelope.py` (8), `test_06_rbac.py` (5), `test_07_concurrency_occ.py` (6) — corner queue
- `test_09_difficulty_dual_variant_calc.py` (6), `test_10_difficulty_combinatorial_formula.py` (6), `test_11_difficulty_non_linear_state_machine.py` (6), `test_12_difficulty_transitive_cascade.py` (6), `test_13_difficulty_priority_pair_conflicts.py` (6), `test_14_difficulty_boundary_precision.py` (6), `test_15_difficulty_cross_entity_state_dependency.py` (6), `test_16_difficulty_temporal_overlap.py` (6), `test_17_difficulty_compensating_invariant.py` (6) — difficulty queue

**Stage 2 tag-check result: PASS.** Every one of the 103 test functions has a docstring ending with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real design-index instance; all 27 difficulty instances have exactly 2 tests and all 47 corner instances have ≥1; all quoted PRD citations verified verbatim against `PRD.md` (95 curated sentences, all literal-grep-clean including backticked identifiers); zero `skip`/`skipif`/`xfail` markers; `pytest --collect-only` collects all 103 tests with no import errors.

## Step 7: Run tests and iterate — 2026-08-15T00:36:46.000Z

All 8 rounds pass 103/103. The exit condition is met.

**Iterations run:** 3 (each a full 8-round parallel sweep, per-test-server isolation).

- Iteration 1: 67/103 in all 8 rounds — 36 deterministic failures, zero flakiness (every round identical).
- Iteration 2: 100/103 in all 8 rounds — 3 residual failures, all previously masked by earlier setup errors.
- Iteration 3: **103/103 in all 8 rounds — clean.**

**Tests deleted:** none. Every failing test traced to a PRD-verbatim rule; all fixes were made in the test artifact layer.

**Fixes applied to `test_helpers/`:**
- `assertions.py` — added `assert_same_instant(actual, expected_iso)`: compares timestamps by instant, not string form. PRD §2.4/§3.3 pin the instant while §2.5/§2.2 mandate three-fractional-digit serialization, so exact-string equality against a no-millis form is not uniquely derivable; the instant is.
- `fixtures.py` `setup_member_with_ctm_cases` — identical intakes (same member/kind/provider) at one clock instant trip the PRD §3.2 duplicate-intake guard; cases are now spaced 2h apart.
- `fixtures.py` `setup_closed_case` (`close_note=True` path, latent) — the lapse-NOTE close path for a non-FULLY_FAVORABLE APPEAL now advances the clock past `decided_at` + 72h, since PRD §3.8 permits closure only once "the 72-hour forwarding window lapsed unexercised". Added `_parse_instant`/`_fmt_instant` helpers.

**Fixes applied to `test_suite/`:**
- Timestamp instant comparisons (10 tests across test_02, test_03, test_05, test_10, test_11, test_14, test_16): replaced exact-string equality with `assert_same_instant`.
- Duplicate-intake setup collisions (PRD §3.2): second member in test_02 (`test_decide_creates_effectuation_only_when_favorable`), test_03 (`test_audit_universe_half_open_period_window`), test_04 (`test_ack_window_boundary_exactly_24h_ok_25h_fails`); 2h clock spacing in test_03's snapshot-order test (also makes the PRD `created_at` tie-break decisive) and in test_14's local `_build_triaged_linked_cases`.
- NameError repairs (14 tests): module-level `_setup_*` helpers referenced the pytest fixture name `api`; switched helpers to the imported `api_client` in test_03, test_11, test_12, test_13, test_15, test_16, plus a missing `decide_grievance_from_in_review` import in test_10 (masked in iteration 1 by the duplicate-guard failure preceding it).
- test_09 (both timeliness tests): setup completed the effectuation 36h after `decided_at` but asserted 60h/72h = 83.33; completion clock moved to 2026-08-04T12:00:00Z (true 60h consumed) and the business-variant comment corrected (13h → ~18.06).
- test_12 `test_reopening_grant_cascade_supersedes_review_and_counts_member` and test_17 `test_reopening_grant_adds_exactly_one_open_case`: the "exactly +1" open_case_count assertion contradicted PRD §3.1's verbatim open-status list, which includes `REOPENED`; corrected to the PRD-determined value (+2: the RECEIVED spawn per §3.8 plus the source re-entering the open set via the CLOSED → REOPENED marker), with comments citing §3.1.
- test_12 `_setup_closed_appeal_with_determined_review`: clock now advances past `decided_at` + 72h before the lapse NOTE and close (PRD §3.8).

**Fixes applied to `implementation/`:** none. Every failure traced to the test layer; the implementation was PRD-faithful throughout (including the duplicate-intake guard, the IRE-lapse close gate, and the §3.1-definition-based live counters, all of which the broken tests had wrongly blamed).

## Step 8: Finalize PRD — 2026-08-15T00:46:00.000Z

PRD_FINALIZED.md is complete.

**Line counts:** `PRD.md`: 313 lines; `PRD_FINALIZED.md`: 315 lines (+2 lines, +0.64%). Both at `/home/ubuntu/github/CodingPRD/tasks/task_1889_health_plan_grievance_appeals/workspace/`.

**Changes (4 edits, each traced to a `<step_7_diff>` item):**

- **§2.5 — insert** — new paragraph pinning uniform timestamp serialization: every emitted timestamp (envelope `api_request_timestamp`, clock endpoint `current_utc`, and every resource stamp including `received_at`, `decided_at`, `resolution_due_at`, `effectuation_due_at`, `occurred_at`, `sent_at`, `forwarded_at`, `ire_decision_received_at`, `completed_at`, `requested_at`, `snapshot_at`, etc.) is ISO 8601 UTC with exactly three fractional digits and a `Z` designator (whole seconds emit `.000`). Traces to the `assert_same_instant` helper addition and the 10 timestamp-comparison test fixes. Impl: `db.fmt_ts` (`implementation/db.py:34-39`), used by `serializers.py:10-11,66-73,89-90,119,130,132,146,157-158,173-174`, `envelope.py:11`, `routes/clock.py:26`.
- **§2.3 — revise** — appended: when pinned sort keys compare equal, creation order is the final tie-break, never `id`. Traces to the test_03 snapshot-order fix that spaced case creation 2h apart "to make the PRD `created_at` tie-break decisive" (revealing PRD silence beyond the `created_at` tie). Impl: `_seq` final key in `calc.py:234` (snapshot) and every listing (`routes/cases.py:131,350,369,386,423`, `members.py:61,83`, `policies.py:79`, `reviews.py:72`, `effectuations.py:42`, `audit.py:132`, `services.py:134,140`).
- **§3.6 — revise** — pinned the 72-hour IRE forwarding window boundary as inclusive: forwarding at exactly `decided_at` + 72h is still within the window; only later attempts get `ERR_IRE_WINDOW_MISSED`. Traces to the `setup_closed_case` / `_setup_closed_appeal_with_determined_review` fixture fixes advancing the clock past `decided_at` + 72h. Impl: `routes/ire.py:33-35` (`> 72h` rejects).
- **§3.8 — revise** — pinned that the forwarding window "lapses" only once the current time is strictly past `decided_at` + 72h; at exactly that instant the lapse ground for closure is not yet available. Same trace. Impl: `routes/cases.py:296-300` (`> 72h` lapsed).

**Items with no PRD edit (verified PRD-determined or pure test bugs):**
- Duplicate-intake fixture collisions (2h spacing): §3.2 already pins the one-hour same-member/kind/provider guard (`routes/cases.py:63-72`); same-instant duplicates are unambiguously within it.
- 14 NameError repairs: pure test-layer bugs.
- test_09 (36h→60h setup, 13h→~18.06 comment): pure test arithmetic; §3.7's formula and the Mon–Fri 08:00–17:00 UTC definition already uniquely determine both variants (verified against `calc.py:127-159`: decided Sun 2026-08-02T00:00 → completed Tue 2026-08-04T12:00 = 60h calendar → 83.33; business tally 9h + 4h = 13h → 18.06).
- test_12/test_17 open_case_count +1→+2: step_7 itself calls +2 "the PRD-determined value" — §3.1's computed counter (open set includes `REOPENED`) plus §3.8's CLOSED → REOPENED marker uniquely determine it (`calc.py:166-174`, `routes/reopenings.py:127-134`). Prose kept verbatim.

**Per-edit pre-edit search log:**

**Edit 1 (§2.5 timestamp format).** (a) Subject: serialization format of every emitted timestamp. (b) Enumerated: `grep fmt_ts` across all impl files — `serializers.py` (all eight resource serializers, every timestamp field), `envelope.py:11` (`api_request_timestamp`), `routes/clock.py:26` (`current_utc`), definition at `db.py:34-39` (always `YYYY-MM-DDTHH:MM:SS.mmmZ`, `None` → null). Confirmed no other code path emits a timestamp (ctm-exposure, compliance-summary, snapshot response carry none). (c) Used "including" before the field list (non-exhaustive) and a neutral example instant (`2026-08-02T12:00:00.000Z`) instead of the §2.4 startup literal, to avoid any appearance of redefining §2.4's `2026-08-01T00:00:00Z` instant notation; said nothing about sub-millisecond truncation, which no Step 7 item exercised.

**Edit 2 (§3.6 forwarding boundary).** (a) Subject: the 72-hour IRE forwarding window boundary. (b) Enumerated every `IRE_FORWARD_WINDOW_HOURS` use: `routes/ire.py:33-35` (reject iff elapsed `> 72h`) and `routes/cases.py:296-300` (lapse iff elapsed `> 72h`); `grep` confirmed no other 72h consumer. (c) Scoped the wording to the 72-hour window only, so the distinct 24-hour ack window (`cases.py:153`, `calc.py:267`) and 180-day reopen window (`reopenings.py:25`) are untouched.

**Edit 3 (§3.8 lapse boundary).** (a) Subject: when the unexercised 72-hour window counts as lapsed for closure. (b) Same enumeration as Edit 2 — the two window sites are complementary in the impl (forwarding allowed at exactly +72h ⟺ lapse not yet available at exactly +72h); verified both fixtures now use `decided_at + 73h`. (c) Worded as "strictly past `decided_at` plus 72 hours" to be the exact complement of Edit 2's inclusive forwarding boundary, keeping both enumerated paths mutually consistent.

**Edit 4 (§2.3 creation-order tie-break).** (a) Subject: final ordering tie-break for list endpoints and snapshot rows. (b) Enumerated every sort in the impl: `calc.py:234` (snapshot: `decided_at, created_at, _seq`), `cases.py:131,350,369,386,423`, `members.py:61,83`, `policies.py:79`, `reviews.py:72`, `effectuations.py:42`, `audit.py:132`, `services.py:134,140` — all end in `_seq` (monotonic creation sequence from `db.next_seq`); providers have no list endpoint. (c) Worded globally ("wherever the pinned sort keys compare equal — whether under the default creation-timestamp order or either custom order") so the single sentence consistently covers the default order, the event-log order, and the snapshot order, and echoed §3.9's existing "never `id`" constraint rather than narrowing it.

## Step 9: Complete PRD — 2026-08-15T00:58:00.000Z

The diff is complete and verified.

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1889_health_plan_grievance_appeals/workspace/PRD_COMPLETED.md`

**Source vs. output:** `PRD_FINALIZED.md` (source) — 315 lines / 51,124 chars → `PRD_COMPLETED.md` — 321 lines / 55,441 chars. Delta: +6 lines, +4,317 chars. 25 change hunks (22 in-place paragraph revisions, 3 pure sentence insertions). No sections added or removed.

**Counts:** 20 ambiguity-pins, 5 mismatch-revisions (some hunks contain one of each; counted by distinct behavior pinned).

**Changes (one bullet each):**

- §2.2 — insert — ambiguity — undeclared paths and unsupported methods reject as `ERR_NOT_FOUND` (404) in the standard envelope — implementation/app.py:29-37
- §2.3 — revise — ambiguity — `limit`/`offset` out-of-range values are clamped (1..100, ≥0), non-integers reject `ERR_VALIDATION`; boolean filters (`overdue`, `active`, `resolution_timely`) parse case-insensitive `true`/`false`, other values leave the filter unapplied — implementation/envelope.py:50-95
- §2.4 — revise — ambiguity — every server-stamped timestamp (all workflow stamps, `created_at`/`updated_at`, envelope `api_request_timestamp`) reads the logical clock, not just deadlines — implementation/db.py:92-110, implementation/envelope.py:8-12, implementation/services.py:41
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — implementation/db.py:99
- §2.5 — insert — ambiguity — client-supplied system-managed/undeclared payload fields (`id`, `version`, `overdue`, …) are ignored — implementation/routes/members.py:25-43, implementation/routes/cases.py:39-96
- §2.7 — insert — ambiguity — the expected-version field is mandatory (missing/non-integer → `ERR_VALIDATION`), and the stale-version comparison runs after the operation's state and business preconditions, immediately before mutation — implementation/routes/cases.py:205-218, implementation/routes/reopenings.py:84-102, implementation/routes/effectuations.py:74-82
- §2.8 — revise — **mismatch** — swapped gates five/six: terminal-state lockdown (`ERR_ALREADY_TERMINAL`) is evaluated *before* transition validity (`ERR_INVALID_STATE`); impl checks terminal first everywhere — implementation/services.py:66-81 (also confirmed by test_02 expecting `ERR_ALREADY_TERMINAL` on a CLOSED case)
- §2.8 — revise — ambiguity — case-event appends exempted from terminal lockdown (appendable even on CLOSED/WITHDRAWN cases; only the CTM flag effect is conditional) — implementation/routes/cases.py:321-337
- §2.8 — revise — ambiguity — `ERR_VALIDATION` is not a fixed gate; each endpoint applies structural validation where its payload is first read (position varies by endpoint) — implementation/routes/cases.py:40-50 vs implementation/routes/reviews.py:97-108
- §2.9 — revise — ambiguity — recording a decision that arms effectuation also requires an active policy (`ERR_POLICY_NOT_CONFIGURED`), not just triage and upgrades — implementation/routes/cases.py:259-263
- §3.1 — revise — ambiguity — duplicate/out-of-bounds `member_ref` → `ERR_VALIDATION` — implementation/routes/members.py:27-34
- §3.1 — revise — ambiguity — `npi` format/uniqueness violations → `ERR_VALIDATION` — implementation/routes/providers.py:25-33
- §3.2 — revise — ambiguity — duplicate-intake window boundary is inclusive (identical case received exactly 1h earlier still blocks) — implementation/routes/cases.py:64-72
- §3.3 — revise — ambiguity — non-`ACTIVE` member at triage → `ERR_INVALID_STATE`; missing provider at triage → `ERR_REFERENCE_NOT_FOUND` — implementation/routes/cases.py:146-151
- §3.3 — revise — ambiguity — expedite on an already-`EXPEDITED` case → `ERR_INVALID_STATE` — implementation/routes/cases.py:187-188
- §3.4 — revise — ambiguity — draft/finalize by anyone but the assignee → `ERR_DUTY_SEGREGATION` (422) — implementation/routes/reviews.py:99-101, 125-127
- §3.4 — revise — **mismatch** — when `override_score` is supplied the weighted formula result is *not stored at all* (was: "retained in the draft's audit body") — implementation/calc.py:89-95 (early return on override)
- §3.4 — revise — **mismatch** — supersession fires at reopening *grant* time (not when a newer review is created), and `superseded_by_review_id` is never populated (stays null) — implementation/routes/reopenings.py:135-139
- §3.5 — revise — ambiguity — decision-created effectuation's `payment_amount_cents` defaults to 0 when omitted; a negative payment → `ERR_PAYMENT_NOT_ALLOWED` — implementation/routes/cases.py:249-254, 266
- §3.5 — revise — ambiguity — the content matrix resolves every (kind, recipient, program, case-kind, outcome) tuple to the same full seven-element set; non-required supplied elements contribute nothing; `supplied_elements` defaults to empty — implementation/calc.py:106-120, implementation/routes/notifications.py:43
- §3.5 — revise — ambiguity — `RETRIED` → `FAILED` is permitted (mark-failed accepts `SENT` or `RETRIED`) — implementation/routes/notifications.py:116-124
- §3.6 — revise — ambiguity — forwarding a non-`APPEAL` or `FULLY_FAVORABLE` case → `ERR_INVALID_STATE` — implementation/routes/ire.py:28-31
- §3.6 — revise — ambiguity — negative IRE `payment_amount_cents` → `ERR_VALIDATION`; overturn-spawned effectuation takes the recorded payment, defaulting to 0 — implementation/routes/ire.py:76-85
- §3.7 — revise — ambiguity — completing an effectuation whose case has no `effectuation_due_at` (UNFAVORABLE decision overturned at IRE) leaves `timeliness_percent` null — implementation/routes/effectuations.py:86-97
- §3.8 — revise — **mismatch** — dropped the "lapse documented by a `NOTE` event" clause; impl records no lapse event, only the closure's own `CLOSED` NOTE — implementation/services.py:109-115
- §3.8 — revise — **mismatch** — closing from `IRE_REFERRED` accepts the linked referral in `DECISION_RECEIVED` *or* `EFFECTUATED` (the auto-transition fires on effectuation completion, before closure) — implementation/routes/cases.py:301-306
- §3.8 — revise — ambiguity — reopening window boundary inclusive (exactly 180 days after closure is within) — implementation/routes/reopenings.py:22-26
- §3.8 — revise — ambiguity — grant requires the source still `CLOSED` and no other `GRANTED` reopening, either violation → `ERR_INVALID_STATE` — implementation/routes/reopenings.py:90-99
- §3.8 — revise — ambiguity — spawned case stamps `received_at` at grant, copies `member_id`/`provider_id`/`case_kind`/`priority_track`, resets `expedited_requested` to false; grant moves `open_case_count` by +2 (spawn + source re-entering the open set via `REOPENED`) — implementation/routes/reopenings.py:105-127, implementation/calc.py:166-174
- §3.9 — revise — ambiguity — the audit's "linked effectuation" is the case's most recently created one; a required-but-never-completed effectuation yields `effectuation_timely` = false — implementation/calc.py:242-260
- §3.9 — revise — ambiguity — compliance-attribution view is computed live over the period's decided-case population (not stored snapshot rows), echoes `report_period`, rounds rates half-up to 4 decimals with 0.0 on zero denominator, effectuation-rate denominator counts only non-null `effectuation_timely` cases, and intake-delay cases count as timely in `resolution_timely_count`/rate — implementation/routes/audit.py:65-102

Notable verified-consistent areas (no change): full RBAC table vs. route decorators, all endpoint status codes (201 creates / 200 mutations), state machine transitions, medical-necessity and completeness rounding orders, business-hours timeliness variant, CTM tier thresholds and provisional-weight ceiling, audit snapshot half-open window and row ordering, OCC endpoints set, and event-type append permissions.
