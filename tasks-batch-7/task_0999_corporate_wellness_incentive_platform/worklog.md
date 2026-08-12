# Worklog — task_0999_corporate_wellness_incentive_platform

## Step 1: Create Task Directory — 2026-08-09T17:20:00.000Z

Task directory `tasks/task_0999_corporate_wellness_incentive_platform/` and its `workspace/` subdirectory pre-assigned by the headless run invocation; verified present on disk. Step 1 auto-index scan skipped per instructions.

## Step 2: Generate Scaffold — 2026-08-10T13:47:00.000Z

All checks pass. Scaffold generation complete.

## What was generated

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_0999_corporate_wellness_incentive_platform/`

**Files:**
- `SCAFFOLD.yaml` — §1.0–§1.7 plus preamble (`scenario`, `domain_name: corporate-wellness-incentives`, `api_prefix: /wellness`, `complexity_profile`, fixed `response_envelope`); does NOT contain `scaffold_difficulty_design` or `scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

**Structural summary (verbatim counts):**
- **Entities: 14** — Employer, Employee, WellnessProgram, Enrollment (parallel state dimensions: participation × verification), HealthAssessment, BiometricScreening, Challenge, ChallengeParticipation, ActivityEvent (idempotency-keyed device ingest), PointsLedgerEntry, IncentiveAward, CoachingReferral (cyclic re-referral), VendorInvoice, AggregateReport (k-anonymity gated)
- **State machines: 11** (42 transitions), including a cyclic referral loop, a branching dispute loop on awards, parallel enrollment axes, and clock-swept auto-transitions (challenge completion, screening NO_SHOW, ledger expiry)
- **Calculations: 9** — incl. dual variants (provisional vs settled points; STANDARD vs REASONABLE_ALTERNATIVE premium differential), pinned per-line-then-sum invoice rounding, tier attainment with cap clamp
- **Validations: 11** priority rows (auth → authz → existence/schema → OCC → ownership → state → business_safety → constraint → temporal → referential → fiscal)
- **Endpoints: 65** (42 mutations, 23 GETs; includes `POST /_clock/set_current_utc` with pinned default 2026-05-01T00:00:00Z); every FK has a reverse-reachability GET
- **Error catalog: 28** codes
- **Roles: 5** — PlatformAdmin/BenefitsAdmin/Coach/VendorManager (opaque), Employee (`entity_backed:Employee`); segregation-of-duties on invoice submit↔approve
- **Concurrency rules: 2** (OCC on Enrollment and Challenge versions, ERR_STALE_VERSION/412)
- **§1.8: 18 instances** (9 rules × 2, all differentiation clauses honored; all formula-derived asserts pre-computed, e.g. RA award 36000 vs standard 0; invoice lines 4839+4839=9678 vs rejected 9677)
- **§1.9: 46 declared** (42 active + 4 `excluded_because` stubs resolving to §1.8 instances); instance names unique across both files (64 total)

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(Coverage: 65 endpoints, 14 entities, 18 §1.8 instances, 42 §1.9 instances, 541 calls scanned.)

Two syntax repairs were applied during lint iteration (quoted `$.data[0].x` capture paths and `errors[...]`/`validations[...]`/`concurrency_rules[...]` grounds refs to satisfy YAML flow-context rules); one forbidden-vocabulary instance ("simultaneous") reworded. No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-08-10T13:48:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_0999_corporate_wellness_incentive_platform/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T14:00:00.000Z

PRD generation complete. Verbatim summary:

## Generated artifact

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_0999_corporate_wellness_incentive_platform/workspace/PRD.md` — 344 lines, 7,381 words. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no other `tasks/task_*/` directory was read.

## Section list

- **§1. Introduction** — 2 paragraphs (business context, then full operating-loop scope; `/wellness` mount mentioned here, allowed outside §3)
- **§2. Global Specifications & System-Wide Principles** — 11 subsections:
  - 2.1 User and Role-Based Access Control (headers, 5 roles, per-role `identity:` translations: `Employee` entity-backed; `PlatformAdmin`/`BenefitsAdmin`/`Coach`/`VendorManager` opaque with `assigned_coach_id`/`submitted_by` recording semantics)
  - 2.2 API Response Structure — **verified byte-identical verbatim paste** of `section-2.2-response-structure.md` (script check: `True`)
  - 2.3 Pagination (`limit` default 10 / min 1 / max 100, `offset` default 0, `created_at` ascending, meta fields)
  - 2.4 Common Resource Properties (UUID `id`, `created_at`/`updated_at` 3-fractional-digit UTC, `version`; explicit exemption of HealthAssessment and ActivityEvent — `common_fields: false` — carrying only `id`+`created_at`)
  - 2.5 The Logical Clock and Time-Driven Sweeps (default `2026-05-01T00:00:00Z`, `to_iso8601`/`now`, all three sweep rules)
  - 2.6 Request Evaluation Order (all 11 validation priorities as an ordered list with named error IDs, incl. SoD-before-fiscal consequence)
  - 2.7 Optimistic Concurrency Control (both OCC rules: `expected_enrollment_version` on adjustments, `expected_challenge_version` on challenge edit, `ERR_STALE_VERSION`/412, no race framing)
  - 2.8 The Dual-View Points Ledger (kinds, statuses, ADJUSTED-born-POSTED, both balance definitions, EXPIRED excluded)
  - 2.9 Money, Rates, and Rounding Discipline (integer cents, half-up cap product, 2dp/4dp report rounding, pinned per-line invoice rounding with the sum-then-round alternative explicitly rejected)
  - 2.10 Nested Resource Retrieval (left-to-right 404)
  - 2.11 Privacy Safeguards and Segregation of Duties (k-anonymity, SoD)
- **§3. Business Logic & Workflows** — 9 subsections: 3.1 Employer Onboarding & Population, 3.2 Program Configuration & Plan-Year Lifecycle (incl. pinned close ordering: challenge sweep first, ledger expiry second, screening no-show third), 3.3 Enrollment & Two Independent Status Axes, 3.4 HRA & Biometric Screening, 3.5 Challenges/Device Sync/Points Accrual (rates, 100/day cap, idempotency triple, backfill, completion cascade), 3.6 Coaching Referrals & Re-Referral Loop, 3.7 Incentive Awards & Premium Differential (tier attainment, cap, RA variant, surcharge waiver, dispute/resolve loop), 3.8 Vendor Billing & Invoice Governance, 3.9 De-Identified Cohort Reporting
- **§4. Endpoint Definitions** — status-code paragraph (201 creates / 200 modifications / 200 idempotent replay) + 4-column table with all **65 endpoints** (matches scaffold count exactly)
- **§5. Error Code Catalogue** — 2-column table with all **28 error IDs** and HTTP statuses

## Hard Contract verdicts (all verified by script)

- **Contract 1 (Field-Name Coverage): PASS** — `entities[].fields`: 87 required, 87 present, 0 missing; `endpoints[].input`: 64 required, 64 present, 0 missing; query params (`limit`, `offset`): 2/2 present. (First script run was a false negative caused by code-fence backtick pollution; re-run with fences stripped passed, and stayed green after fixes.)
- **Contract 2 (Rule Coverage): PASS** — manual walk of all six high-risk categories plus the tail: 11/11 validation priorities expressed as explicit ordering; 2/2 OCC rules with write capability + occ field + error id + 412; 45/45 state-machine transitions with preconditions and side effects (incl. close-sweep ordering, verification-axis independence, rerefer resets); 8/8 calculations in reconstruction-safe prose (no pseudocode, no fuzzy words — both linted clean); 28/28 error IDs mentioned in §2/§3 prose; sibling branches symmetric (3 terminate sources, 2 rerefer sources, UPHELD/ADJUSTED, FLAGGED↔VERIFIED); field-level defaults/initials stated (`tobacco_attested` false, `ra_eligible` false at creation, counters start at zero, `terminated_at`/`confirmed_at` null until set).
- **Contract 3 (§3 Path Purity): PASS** — 490 backticked tokens in §3 scanned: 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. Endpoints referenced only via state-pair framing, role+verb, or capability description.
- **Auxiliary checks: PASS** — all 55 enum/state values appear as exact standalone backticked strings; §2.2 verbatim block confirmed byte-identical; no fuzzy/approximating words and no operator syntax (`>=`, `==`, `min(`, `AND`, …) in prose outside backticks.

One caveat for transparency: the first verification script run produced a spurious mass-failure on Contract 1 due to the JSON code fences in §2.2 breaking naive backtick pairing; after stripping fenced blocks the check is reliable and passes.

## Step 5: Generate Unit Tests — 2026-08-10T14:40:00.000Z

Generation complete. Verbatim summary:

## Verdict: PASS — 75 tests collected, all audits green

### Queue A (Difficulty — SCAFFOLD_DIFFICULTY_DESIGN.yaml)
- **17 of 18 instances emitted, exactly 2 tests each = 34 tests.**
- **1 instance SKIPPED:** `priority_pair_validation_conflict/state_beats_temporal_on_terminated_event` — PRD-coverage failure. The instance asserts `ERR_ENROLLMENT_NOT_ACTIVE` for activity-event ingestion against a TERMINATED enrollment, but PRD §3.5's activity-event workflow names only `ERR_EVENT_OUTSIDE_WINDOW`; §2.6 stage 6 applies the specific state errors only "where the workflow names one". A PRD-only implementer could legitimately accept in-window events for terminated enrollments or reject with a different error. Not weakened, not marked skip/xfail — the gap stays a gap.

### Queue B (Corner — SCAFFOLD_CORNER_DESIGN.yaml)
- **40 of 41 non-stub instances emitted, 1 test each = 40 tests.**
- **1 instance SKIPPED:** `entities/activity_event_points_granted_input_ignored` — unique-derivability failure. PRD never states that undeclared request fields are ignored; a strict-schema implementation (400 on `points_granted` in the payload) and an ignore-and-compute implementation are both PRD-faithful.
- **4 `excluded_because` stubs not translated** (as required); all four `difficulty_instance` cross-references verified to resolve: `challenge_completion_exact_goal_boundary` → activity_ingest_transitive_cascade, `award_cap_binds_at_gold` → gold_tier_at_exact_point_threshold, `sod_same_user_approve_rejected` → safety_beats_fiscal_on_invoice_approve, `cascade_visible_immediately_in_response` → activity_ingest_transitive_cascade.

### Helper files written (Stage 1, `test_helpers/`)
`types.py` (25 status/role enums + 15 entity TypedDicts; HealthAssessment/ActivityEvent correctly omit `updated_at`/`version` per PRD §2.4), `api_client.py` (69 endpoint methods subclassing GenericApiClient), `api_errors.py` (28 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity structural assertions + balance/invoice invariants), `factories.py` (input-only payload factories), `constants.py` (daily cap, thresholds, standard fixture values), `test_users.py` (TEST_USERS + per-instance `make_*_headers` builders, Employee entity-backed), `fixtures.py` (composite helpers: setup_active_enrollment, setup_cohort, setup_discharged_referral, setup_confirmed_award, setup_submitted_invoice, add_settled_points, etc.), `__init__.py` (barrel export).

### Test files (Stage 2, `test_suite/`)
`conftest.py` + 11 domain-organized files: 01 population/enrollment, 02 enrollment state & adjustments, 03 program lifecycle, 04 HRA/screening/verification, 05 activity ingest, 06 challenges, 07 incentive awards, 08 coaching, 09 vendor invoices, 10 aggregate reports, 11 access control.

### Lint / stage verdicts
- `python3 -m py_compile` on all 21 files: **OK**
- pytest collection: **75 tests collected**, zero import errors (PYTHONPATH=., no server needed for collection)
- Tag audit: 0 untagged, 0 dual-tagged, 0 dangling tags; every queue-A instance at 2x, every emitted queue-B instance at 1x
- Citation audit: **122 quoted segments ≥8 words each verified verbatim** against PRD.md (whitespace-normalized); 4 initially failing quotes fixed (hyphen line-breaks, stripped markdown bold prefix, trailing-period elision)
- 0 `pytest.mark.skip`/`skipif`/`xfail` markers; 0 "scaffold"/"Table N" references in generated code
- One deliberate weakening inside an emitted instance: `employer_creation_echoes_config` drops the `version == 1` sub-assertion (PRD §2.4 pins "increments by exactly one with every modification" but never the initial value — not uniquely derivable); all eight config-echo assertions retained.

## Step 6: Generate Implementation — 2026-08-10T14:40:00.000Z

Done. Verbatim summary below.

---

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_0999_corporate_wellness_incentive_platform/workspace/implementation/`)

- `start.sh` — executable; guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py`, foreground, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entry point, ApiError/404/405/500 handlers, blueprint registration, `POST /_clock/set_current_utc` (PlatformAdmin-only, runs the §2.5 sweep)
- `db.py` — empty in-memory store (13 entity dicts + request-order sequence counter; no seeding)
- `errors.py` — full 28-ID error catalog with exact HTTP statuses from PRD §5
- `response.py` — envelope helpers: `{meta:{api_request_id, api_request_timestamp}, response_type, data}`; pagination fields `limit/offset/total_count/has_more` in `meta` for lists; error body `{error_id, message}` in `data`
- `clock.py` — logical clock (default exactly `2026-05-01T00:00:00Z`); `stamp_iso()` stamps entity `created_at`/`updated_at` from the logical clock with a monotonic-ms guard (deterministic ascending `created_at` sort)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (stage 1 → `ERR_UNAUTHENTICATED`, stage 2 → `ERR_FORBIDDEN`)
- `services/common.py` — body/schema validation (stage 3), ISO datetime/date parsing, OCC helper ordering, `touch()` (updated_at + version+1 per §2.4), left-to-right path-existence lookups, pagination (default 10, min 1, max 100), employee ownership scope (stage 5)
- `services/serializers.py` — per-entity serializers; HealthAssessment and ActivityEvent emit only `id` + `created_at` (no `updated_at`/`version`, per §2.4)
- `services/cascade.py` — balance recompute (§2.8), participation completion BONUS cascade, challenge/screening clock sweep, close cascade in pinned order (challenges → ledger expiry → screening no-show), tier_attainment + premium_differential (Decimal ROUND_HALF_UP cap), RA recompute
- `services/employers.py`, `employees.py`, `programs.py`, `enrollments.py`, `hras.py`, `screenings.py`, `challenges.py`, `participations.py`, `events.py`, `awards.py`, `referrals.py`, `invoices.py`, `reports.py` — the 13 resource groups

## Endpoint count
57 endpoints total (56 from the scaffold §1.5/PRD §4 table + the `/_clock/set_current_utc` clock driver), all registered and exercised.

## PRD section → code mapping
- §2.1 RBAC → `middleware.require_roles`; Employee scope = `X-User-ID == employee_id` on enrollment-derived resources; Coach scope = `X-User-ID == assigned_coach_id`; SoD records opaque IDs (`submitted_by`, `assigned_coach_id`)
- §2.2/§2.3 envelope + pagination → `response.py`, `common.list_response` (sort by created_at ascending)
- §2.4 common fields → `stamp_new`/`touch`; light resources for HRA/ActivityEvent
- §2.5 logical clock + sweeps → `clock.py`, `cascade.sweep_clock` (PUBLISHED→ACTIVE at `starts_at <= now`, ACTIVE→COMPLETED at `ends_at < now`, SCHEDULED→NO_SHOW at `slot_end < now`)
- §2.6 evaluation order → enforced per-handler: auth → role → existence/schema (path left-to-right outranks body) → OCC (stage 4) → ownership (stage 5) → state (stage 6) → privacy/SoD (stage 7) → uniqueness/overlap/capacity (stage 8) → temporal (stage 9) → referential (stage 10) → fiscal (stage 11)
- §2.7 OCC → `expected_enrollment_version` on adjustments, `expected_challenge_version` on challenge PATCH; both required, 412 `ERR_STALE_VERSION`
- §2.8 dual ledger → `cascade.recompute_balances` (settled = POSTED; provisional = PROVISIONAL+POSTED; EXPIRED excluded)
- §2.9 rounding → Decimal ROUND_HALF_UP; premium cap product and per-line invoice member-months rounded before summation; report aggregates 2dp/4dp half-up
- §3.1 employer/employee → employers.py, employees.py (email unique per employer)
- §3.2 program lifecycle → programs.py (window-overlap with adjacency allowed; close cascade order pinned; settle requires all awards APPLIED; finalize-points counts moved entries)
- §3.3 enrollment axes → enrollments.py (accept ownership+program-ACTIVE, terminate stamps `terminated_at`, adjustments create POSTED ADJUSTED entries)
- §3.4 HRA/screening → hras.py (risk bands 30/60, HIGH auto-referral + count), screenings.py (strict-overlap kiosk capacity before slot-window check, targets_met strict `<`, VERIFIED↔FLAGGED)
- §3.5 challenges/events → challenges.py, participations.py (backfill + immediate completion), events.py (idempotent replay 200 vs `ERR_DUPLICATE_EVENT` 409; floor conversion; 100/day UTC cap by ingestion order; JOINED-cascade completion with `completed_count += 1`)
- §3.6 referrals → referrals.py (engage assigns coach; sessions/discharge assigned-only; discharge ≥ required sessions → `ERR_REFERRAL_SESSIONS_INSUFFICIENT`; GOALS_MET on ra_eligible recomputes the PROJECTED award; rerefer increments round, resets sessions/outcome/coach, preserves lifetime `session_dates`)
- §3.7 awards → awards.py (compute per ACTIVE/SUSPENDED enrollment; PROJECTED upserted, CONFIRMED/APPLIED/DISPUTED untouched; confirm requires CLOSED + computed-after-close via a request-order sequence counter; dispute window `now <= confirmed_at + 30d`; resolve UPHELD/ADJUSTED refreshes `confirmed_at`)
- §3.8 invoices → invoices.py (inclusive period days; per-line half-up proration; TERMINATED billed through termination date when ≥ period_start; coaching lines from lifetime `session_dates`; DRAFT-only adjustments; SoD before limit guard; dispute→revise clears `submitted_by`)
- §3.9 reports → reports.py (CLOSED only; cohort = dept match + ACTIVE/SUSPENDED/TERMINATED; k-anonymity `>=` with nothing persisted on failure)

## Boot-check result
- `bash start.sh` boots and serves HTTP within 1s (60s limit) on a custom `PORT`, binds 0.0.0.0, foreground via `exec`.
- Fresh-boot contract verified twice: store empty (unknown IDs → 404 `ERR_NOT_FOUND`), clock reads exactly `2026-05-01T00:00:00.000Z`, no seeding anywhere in startup code.
- Smoke results: 112/112 end-to-end checks green (full lifecycle: employers→employees→program→enroll→HRA→screenings→challenges→events/caps/idempotency→adjustments/OCC→finalize→coaching loop→awards/dispute/resolve→close→settle→invoices/SoD/limit/override→reports/pagination) plus 22/22 edge checks green (clock sweeps, event-driven completion, suspend/reinstate, RA recompute cascade on existing PROJECTED award, invoice proration exact-split and coaching-line windows, negative adjustments, ledger listings).
- `pyflakes` clean; all modules compile.

## Step 7: Run Tests and Iterate — 2026-08-10T15:10:00.000Z

## Summary

- **Iterations run**: 2 sweeps of 8 parallel rounds each (16 total round-runs).

- **Tests deleted**: None.

- **Fixes applied to `test_helpers/`**:
  - `test_helpers/fixtures.py` — `setup_verified_enrollment()`: after submitting the HRA, re-read the enrollment via `GET /wellness/enrollments/{id}` so the returned context reflects the post-HRA verification axis. Previously the fixture returned the pre-HRA enrollment snapshot (still `verification_status == "PENDING"`), so any test asserting on `ctx["enrollment"]["verification_status"]` after the fixture saw the stale value. The bug surfaced as `AssertionError: assert 'PENDING' == 'VERIFIED'` in `test_02_enrollment_state_and_adjustments.py::TestParallelStateDimensions::test_suspend_preserves_flagged_verification` (and would have hit the sibling `test_reinstate_preserves_flagged_verification` and `test_04_hra_screening_verification.py::TestBiometricTargets::test_biometric_targets_strict_less_than` on the same fixture path). One fixture fix, three downstream tests protected.

- **Fixes applied to `implementation/`**: None. The implementation's HRA handler already performs `PENDING → VERIFIED` correctly per PRD §3.4 ("Creating a member's first HealthAssessment moves `PENDING → VERIFIED` automatically."). The failure was purely a fixture staleness issue.

- **Final sweep verdict**: Round 1: 75/75, Round 2: 75/75, Round 3: 75/75, Round 4: 75/75, Round 5: 75/75, Round 6: 75/75, Round 7: 75/75, Round 8: 75/75 — all 8 rounds clean.

Files touched:
- `/home/ubuntu/github/CodingPRD/tasks/task_0999_corporate_wellness_incentive_platform/test_helpers/fixtures.py` (one edit, `setup_verified_enrollment` re-reads enrollment post-HRA)

## Step 8: Finalize PRD — 2026-08-10T14:41:00.000Z

PRD_FINALIZED.md is written as an exact copy of PRD.md (344 lines each, 0% delta, diff is empty). No edits were made.

## Summary

**PRD.md vs PRD_FINALIZED.md**: 344 lines vs 344 lines, 0% delta. `diff` reports the files identical.

**Changes**: None.

**Rationale**: The single item in `<step_7_diff>` was a pure fixture bug in `test_helpers/fixtures.py` — `setup_verified_enrollment()` returned the pre-HRA enrollment snapshot (still `PENDING`) instead of re-reading the enrollment after HRA submission. The step_7_diff itself explicitly states: "**Fixes applied to `implementation/`**: None. The implementation's HRA handler already performs `PENDING → VERIFIED` correctly per PRD §3.4."

Per the method's rule — "Patch PRD_FINALIZED.md only when impl pinned a choice PRD left open — not every item is a PRD silence (some are pure fixture bugs)" — this fixture-only fix warrants no PRD edit. The behavior was already uniquely pinned by the PRD:
- §3.3: "Creating a member's first HealthAssessment moves `PENDING → VERIFIED` automatically."
- §3.4: "Creation flips the enrollment's verification axis to `VERIFIED`"

And the implementation at `/home/ubuntu/github/CodingPRD/tasks/task_0999_corporate_wellness_incentive_platform/workspace/implementation/services/hras.py:56-58` matches the PRD verbatim. A fresh implementer reading PRD.md alone would produce code behaviorally equivalent at this site.

**Per-edit pre-edit search log**: No edits were committed, so no pre-edit searches were required. The single decision was a *negative* one (do not edit). Supporting evidence gathered:
- (a) Subject considered: HRA submission's effect on `enrollment.verification_status`.
- (b) Impl paths enumerated: `workspace/implementation/services/hras.py` (full read — the only write path for HealthAssessment creation); grep for `VERIFIED|PENDING|verification_status` across `implementation/*.py` and `implementation/services/` confirmed the only mutation sites are `services/hras.py` (PENDING→VERIFIED) and the biometric-screening result path (VERIFIED↔FLAGGED modulation), both already described in PRD §3.3/§3.4.
- (c) Wording adjustment: not applicable — no edit committed.

## Step 9: Complete PRD — 2026-08-10T14:54:00.000Z

All edits are applied. Line count unchanged at 344 (all edits were in-paragraph); char delta is +3815 (58986 − 55171). 29 diff hunks (29 changed lines out, 29 changed lines in = 58 changed-line entries).

## Exit Summary

**Source:** PRD_FINALIZED.md (344 lines, 55171 chars) → PRD_COMPLETED.md (344 lines, 58986 chars). Char-delta: **+3815 chars, +0 lines** (all changes are in-paragraph inserts/revisions; no new sections or paragraphs).

**Counts:** 20 ambiguity-pins (inserts), 7 mismatch-revisions = **27 edits** (the 29 diff hunks include 2 sections touched twice: §2.1 and §2.5).

- §2.1 — insert — ambiguity — pinned that an Employee caller reading another employee's own record or their enrollments listing is rejected `ERR_OWNERSHIP_MISMATCH` (comparison against the employee's own `id`, not a foreign key) — implementation/services/employees.py:44-51, 54-68
- §2.1 — insert — ambiguity — pinned that assigned-coach scope governs only engage/session/discharge writes; any Coach may list an enrollment's coaching referrals — implementation/services/referrals.py:60-67, implementation/services/enrollments.py:209-215
- §2.3 — insert — ambiguity — pinned `ERR_INVALID_REQUEST` for non-integer limit/offset, limit outside 1–100, or negative offset — implementation/services/common.py:248-269
- §2.4 — insert — ambiguity — pinned resources are created with `version` 1 and `updated_at` == `created_at` — implementation/services/common.py:157-164
- §2.5 — insert — ambiguity — pinned the clock may be set to any instant (not necessarily forward) and applied transitions never reverse — implementation/clock.py:21-22, implementation/services/cascade.py:109-122
- §2.5 — insert — ambiguity — pinned that both challenge sweep steps apply in one advance, so a PUBLISHED challenge with a fully elapsed window passes through ACTIVE to COMPLETED in the same advance — implementation/services/cascade.py:113-118
- §2.6 — revise — mismatch — dropped "any end-after-start ordering respected" from stage 3 (impl evaluates end-after-start rules after state checks at several endpoints; per-endpoint orders pinned in §3.2/§3.4/§3.5/§3.8 instead) — implementation/services/programs.py:67-83, screenings.py:38-45, challenges.py:79-98, invoices.py:92-107
- §2.8 — revise — mismatch — dropped the "EARNED and BONUS entries are always positive" claim (an EARNED entry's delta is zero when the daily ceiling leaves no headroom) and pinned null `reason` on EARNED/BONUS entries — implementation/services/events.py:96-116, cascade.py:43-55
- §3.1 — revise — mismatch — "eight financial and policy parameters" → "seven" (only seven are listed and required) — implementation/services/employers.py:19-28
- §3.1 — insert — ambiguity — pinned duplicate email within an employer draws `ERR_INVALID_REQUEST` — implementation/services/employees.py:31-36
- §3.2 — insert — ambiguity — pinned activation evaluates the DRAFT from-state check (`ERR_INVALID_STATE`) before the window well-formedness and overlap rules — implementation/services/programs.py:67-83
- §3.2 — insert — ambiguity — pinned the close no-show sweep covers only screenings of the program's own enrollments — implementation/services/cascade.py:144-149
- §3.2 — revise — mismatch — narrowed the SETTLED lockout from "no new dependent artifacts" to exactly four kinds (invoices, reports, award computations, participations); enrollments, challenges, HRAs, screenings, and activity events are not gated on SETTLED — implementation/services/enrollments.py:20-47, challenges.py:20-51, hras.py:17-75, screenings.py:26-85, events.py:35-135 vs invoices.py:98-102, reports.py:36-40, awards.py:31-35, participations.py:49-54
- §3.3 — insert — ambiguity — pinned enrollment creation requires only program/employee existence: no program lifecycle-state check and no (program, employee) uniqueness rule — implementation/services/enrollments.py:20-47
- §3.3 — insert — ambiguity — pinned the OCC version check runs before the non-zero `points_delta` check on manual adjustments — implementation/services/enrollments.py:137-144
- §3.4 — revise — mismatch — "in the platform's standard evaluation order" → "in this order" (the enumerated sequence ACTIVE → slot well-formed → capacity → plan-year is the actual impl order, not §2.6 numeric stage order) — implementation/services/screenings.py:36-69
- §3.5 — insert — ambiguity — pinned challenge creation rejects `ends_at` not strictly after `starts_at` with `ERR_INVALID_REQUEST` — implementation/services/challenges.py:35-36
- §3.5 — insert — ambiguity — pinned challenge edit evaluates the end-after-start rule against the merged window after the DRAFT-state check, and that an edit carrying only `expected_challenge_version` is accepted and bumps `version` — implementation/services/challenges.py:79-98
- §3.5 — insert — ambiguity — pinned join resolves `challenge_id` before `enrollment_id` and evaluates the enrollment-state check before the challenge-state check — implementation/services/participations.py:26-38
- §3.5 — insert — ambiguity — pinned ingestion requires an ACTIVE enrollment (`ERR_ENROLLMENT_NOT_ACTIVE`), evaluated ahead of quantity positivity (`ERR_INVALID_REQUEST`), idempotency, and the temporal window — implementation/services/events.py:47-87
- §3.5 — revise — mismatch — "zero or one" ledger entries per event → exactly one per accepted event (impl always creates the EARNED entry, even with a zero delta) — implementation/services/events.py:115-116
- §3.5 — insert — ambiguity — pinned that challenge completion (sweep or close) recomputes each still-JOINED participation's `progress_quantity` from the event log before the goal comparison — implementation/services/cascade.py:89-98
- §3.6 — insert — ambiguity — pinned manual referral creation requires only enrollment existence; no enrollment-state precondition — implementation/services/referrals.py:21-42
- §3.6 — revise — mismatch — the RA recompute cascade is recomputed under §3.7's variant-selection rules including the never-declined qualification (was: "recomputed under the reasonable-alternative variant"), and is a no-op when no PROJECTED award exists — implementation/services/cascade.py:235-246, referrals.py:113-114
- §3.7 — insert — ambiguity — pinned the compute endpoint responds 200 OK with the counts object — implementation/services/awards.py:66
- §3.7 — revise — mismatch — pinned the RA-qualifying referral must never have passed through DECLINED (a declined-then-rereferred-then-discharged referral does not confer RA), while the tobacco-cessation surcharge waiver carries no such exclusion — implementation/services/cascade.py:193-212, referrals.py:130-131
- §3.7 — insert — ambiguity — pinned `dispute_reason` is retained on the award after resolution — implementation/services/awards.py:131-133, 152-161
- §3.8 — insert — ambiguity — pinned invoice creation order: program resolution → lifecycle-state rule → period-ordering validation — implementation/services/invoices.py:92-107
- §3.8 — insert — ambiguity — pinned computed MEMBER_MONTH/COACHING_SESSION lines carry null `note`, ADJUSTMENT lines carry null `ref_id`, and `line_items` ordering is member-month lines (enrollment creation order) then coaching lines (referral creation order) — implementation/services/invoices.py:35-79, 138-143
- §3.8 — insert — ambiguity — pinned the TERMINATED eligibility comparison reads the calendar date of `terminated_at` against `period_start` — implementation/services/invoices.py:24-28, 44; enrollments.py:45
- §4 — revise — mismatch — logging a coaching session returns 201 Created (was covered by "modify → 200 OK"); also pinned (ambiguity) that a manual enrollment points adjustment returns 201 with the created ledger entry — implementation/services/referrals.py:87, enrollments.py:150

Notes on judgment calls: tests were treated as cross-reference only per instructions. Deep impl artifacts deliberately not pinned as PRD prose: the rejected challenge-edit window validation mutates stored fields before raising (challenges.py:83-96, no version bump) — judged an impl bug artifact rather than a spec-level behavior; and the ZeroDivisionError edge for `k_anonymity_threshold` of 0 (reports.py:59-65) — no valid PRD-level reading to pin.
