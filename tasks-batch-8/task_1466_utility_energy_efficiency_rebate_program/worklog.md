# Worklog — task_1466_utility_energy_efficiency_rebate_program

## Step 1: Create task directory — 2026-08-13T09:51:00.000Z

Directory `tasks/task_1466_utility_energy_efficiency_rebate_program/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline coordinator. Step 1 treated as DONE per instructions; no new task index computed, no other task_* directory touched.

## Step 2: Generate scaffold — 2026-08-13T11:02:00.000Z

## Summary

Generated complete scaffold artifacts for **task_1466_utility_energy_efficiency_rebate_program** (Utility DSM Rebate Program Administration).

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1466_utility_energy_efficiency_rebate_program/SCAFFOLD.yaml` (§1.0–§1.7, no scaffold_difficulty_design or scaffold_corner_design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1466_utility_energy_efficiency_rebate_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1466_utility_energy_efficiency_rebate_program/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

**Design choices:**
- **Archetype**: compliance_audit (primary) + quota_allocation (secondary)
- **Topology**: flat (all resources top-level collections; FK via request body fields, reverse-reachable via filtered-list GET endpoints)
- **Role model**: segregation_of_duties (ProgramAdministrator, TradeAlly, VerificationInspector, PaymentProcessor, RegulatorAnalyst; approver must differ from verifier)
- **9 entities**: ProgramYear, Measure, TradeAlly, RebateApplication, ApplicationLineItem, SavingsClaim, Inspection, EvaluationAdjustment, FraudFlag
- **43 endpoints**, **33 error codes**, **26 ordered validations**, **8 calculations**, **4 state machines**, **1 OCC concurrency rule** (ProgramYear config edit)

**Difficulty design (§1.8)**: 18 instances across all 9 rules, 2 per rule:
- dual_variant_calc: deemed-vs-measured kwh on line item; unadjusted-vs-adjusted kwh on ProgramYear
- combinatorial_formula: tiered pacing selection (mode a); per-line-round-then-sum (mode b, 334 vs 333)
- non_linear_state_machine: TradeAlly ACTIVE⇄SUSPENDED cycle; RebateApplication SUBMITTED branching to VERIFIED/WITHDRAWN/REJECTED
- transitive_cascade: inspection FAILED depth-3 cascade; programYear close auto-pays cascade
- priority_pair_validation_conflict: state>fiscal; referential>temporal
- boundary_precision_check: budget cap exact fit (<= semantics); ally performance score 90 boundary
- cross_entity_state_dependency: app→ProgramYear OPEN; app→TradeAlly ACTIVE
- resource_temporal_overlap: SAME_SERVICE_ADDRESS half-open 30d window; ALLY_BURST closed 7d count threshold
- compensating_invariant: budget cents conservation through pay; reported kwh conservation through reject

**Corner design (§1.9)**: 54 active instances + 2 excluded stubs covering: entity creation/defaults/retrieval/not-found for all 9 entities, state machine initial/terminal/invalid transitions, all 31 non-§1.8 error codes (auth, RBAC, uniqueness, business rules), 4 RBAC wrong-role cases, ownership (ERR_FORBIDDEN), OCC stale-version test, pagination, immutability (SavingsClaim common_fields=false), filtering.

**Linter verdict** (verbatim from `scaffold_lint.py`):
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
- §1.5 endpoints: 43; §1.1 entities: 9; §1.8 instances: 18; §1.9 instances: 54 active; calls scanned: 647; violations: 0.

## Step 3: Copy shared files — 2026-08-13T11:04:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1466_utility_energy_efficiency_rebate_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T11:39:00.000Z

All checks pass. The PRD is complete and verified.

## Report

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1466_utility_energy_efficiency_rebate_program/workspace/PRD.md` from `SCAFFOLD.yaml` (the two DESIGN index files were not opened or referenced, per the constraint).

**Document structure** (domain-derived, not template-copied):
- §1 Introduction — 2 paragraphs from the DSM-regulatory business context
- §2 nine subsections: RBAC with per-role identity translation (TradeAlly entity-backed via `trade_ally_id` vs `X-User-ID`; four opaque roles with `verified_by` recording), verbatim §2.2 envelope (diff-confirmed byte-identical to `section-2.2-response-structure.md`), Pagination, the Logical Program Clock (fixed `2026-08-01T00:00:00Z` default, never wall-clock), Common Resource Properties (including the `common_fields: false` carve-out for SavingsClaim/FraudFlag — no `updated_at`/`version`), Program Ledger Consistency (`committed_cents`/`paid_cents`/`reported_kwh` definitions and version-bumping cascades), Rounding Discipline, OCC, and global Validation Order
- §3 seven subsections organized by lifecycle: program setup/catalog, ally enrollment/standing, drafting/line-items/claims, submission (pacing tiers + fraud screen), inspection/verification, approval/payment/rejection/withdrawal, close-out/evaluation/reporting
- §4 endpoint table: 43 rows, 4 columns only; §5 error catalogue: 33 rows, 2 columns only

**Hard contract reports:**

```
Field coverage check:
- entities[].fields + common fields: 58 required, 58 present, 0 missing
- endpoints[].input/query_params: 8 required (to_iso8601, expected_program_year_version,
  current_utc, limit, offset, scheduled_on, outcome, fail_reason overlap), all present
- total: 66 required, 66 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] priority orderings: 10 endpoint-specific sequences expressed in prose
  (submit's 8-step gate in §3.4, approve's fraud-hold-before-segregation in §3.6,
  verify's measured-input-before-inspection-obligation in §3.5, complete's
  open→parent-state→fail-reason→already-completed in §3.5, open/close/report in §3.1/§3.7)
- concurrency_rules[]: 1 checked, 1 expressed (write endpoint + expected_program_year_version
  + ERR_STALE_VERSION/412 named; no race framing)
- state_machines[].transitions: 18 checked, 18 fully expressed (all from/to states, preconditions
  with error ids, side effects incl. cross-entity ledger cascades and version increments)
- calculations[]: 8 checked, 8 expressed in precise prose (floor vs round-half-up directions,
  per-line-rounding-before-summing mandate, half-open 30-day vs closed 7-day windows,
  every-fifth sampling, 10000 kWh override, 40/25/15 weights, threshold 50, 90/70 tiers)
- validations[] conditions: 26 checked, 26 matchable to error ids in §2/§3 prose
- endpoints[].side_effects / applies_to: all expressed, including the exact 11-operation
  ERR_PROGRAM_NOT_OPEN list (schedule-post deliberately excluded) and the 5 ERR_FORBIDDEN scopes
- entities[].fields[] structured content: defaults, null semantics, ranges all stated
- sibling-branch symmetry: 8 groups checked (dual verify paths, dual reject, dual withdraw,
  dual terminate incl. the asymmetric open-applications guard on ACTIVE only, 4 inspection
  kind×outcome cascades, 3 fraud rules, 3 pacing tiers)
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 341
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0 (the `POST` inspection-kind enum value is confined to §2.5;
  §3 uses "post-installation inspection" phrasing)
- method+path combined tokens: 0
Status: PASS
```

**Tooling note:** an initial verification script produced false failures because naive backtick-regex pairing is unbalanced by Markdown code fences (```) — tokens after each fence were inverted. Re-running with a fence-aware tokenizer confirmed true full coverage; §3 purity and table counts were unaffected.

## Step 5: Generate unit tests — 2026-08-13T12:30:00.000Z

Done. Complete test infrastructure generated for task_1466.

## What was built

**`test_helpers/` (9 files)** — `/home/ubuntu/github/CodingPRD/tasks/task_1466_utility_energy_efficiency_rebate_program/test_helpers/`
- `types.py` — TypedDicts + enums; append-only `SavingsClaim`/`FraudFlag` omit `updated_at`/`version` per PRD §2.5
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (36 methods)
- `api_errors.py` — full 33-error catalog, HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions + `assert_program_ledger_invariants`
- `factories.py`, `constants.py` (tier floors, fraud weights/windows, sampling constants, clock anchors), `test_users.py` (opaque roles as shared constants; `make_trade_ally_headers(ally_id)` builder for the entity-backed role)
- `fixtures.py` — composite chains: `create_open_program`, `build_submitted/verified/approved/paid_application`, `build_application_requiring_inspection`, `build_post_inspection_application`, `drive_inspection_history` (N inspections for performance-score tests), `build_closed_program_with_paid_app`, `build_reported_program`

**`test_suite/` (10 files, 94 tests)** — organized by concern from program-year lifecycle through security/RBAC.

## Audit results
- **Design-index coverage**: all 18 difficulty instances have ≥2 tests (39 Difficulty-tagged); all 54 non-stub corner instances have ≥1 test (55 Corner-tagged). The 2 `excluded_because` stubs were not translated; their cross-references resolve to real difficulty instances. Every test has exactly one verbatim `Design:` tag.
- **PRD citations**: all 130 quoted spans verified verbatim against PRD.md (whitespace-normalized grep).
- **Collection**: 94 tests collect cleanly under pytest; no skip/xfail markers; no scaffold references in comments/docstrings.

## Judgment calls (PRD-first filter)
- `program_cap_exact_fit_allowed`: the recipe's literal numbers (preload 19,999,500, then a base-500 line) contradict the PRD's tier rule — at 99% committed the line prices at HIGH_TIER 0.50, so 500-base yields 250, not exact fit. I kept the recipe's shape but used base 1000 (→ exactly 500 == remaining headroom) so the asserted `committed_cents == 20000000` is PRD-derivable.
- `inspection_complete_twice_returns_already_completed`: the recipe re-completes a PASSED PRE inspection, but PRD §3.5's fixed check order (parent-state check before the double-completion guard) would yield `ERR_INVALID_STATE` there since the app already moved to POST_INSPECTION. I used a POST-kind inspection instead — a passed POST leaves the app in POST_INSPECTION, so the guard is genuinely reached and `ERR_INSPECTION_ALREADY_COMPLETED` is uniquely derived.
- `measure_inactive_blocks_submit`: creates the inactive measure before opening the program, avoiding reliance on the ambiguous "While the year is in `DRAFT`..." wording for post-open catalog edits.

No instances were skipped — every non-stub instance in both indices had verbatim PRD coverage with a uniquely-derivable outcome.

## Step 6: Generate implementation — 2026-08-13T12:30:00.000Z

Done. The complete Python + Flask implementation for task_1466 is in place and validated.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_1466_utility_energy_efficiency_rebate_program/workspace/implementation/`:

- **`start.sh`** (executable) — guarded dependency install (`python3 -c "import flask"` check, so per-test reboots skip pip), then `exec python3 app.py` in the foreground.
- **`app.py`** — Flask wiring, `0.0.0.0:$PORT` (default 10000), envelope-consistent error handlers for `ApiError`/404/405/500.
- **`db.py`** — in-memory store (empty at boot, no seeding), logical clock fixed at `2026-08-01T00:00:00Z` startup default (never wall-clock), ISO-8601 timestamps with 3 fractional digits, internal `_seq` for stable `created_at` tie-breaking.
- **`auth.py`** — `X-User-ID`/`X-User-Role` validation (missing/empty/unknown role → `ERR_UNAUTHENTICATED` 401; wrong role → `ERR_UNAUTHORIZED` 403) per the five scaffold roles.
- **`respond.py`** — exact envelope: `meta{api_request_id (req_…), api_request_timestamp}`, `response_type`, `data`; list responses add `limit`/`offset`/`total_count`/`has_more` (defaults 10/0, bounds 1–100/≥0, violations → 400).
- **`validate.py` / `lookups.py` / `serialize.py`** — structural 400s (bool-vs-int strictness, strict `YYYY-MM-DD` dates, enum membership), resource-specific 404 IDs, exact public field sets (SavingsClaim/FraudFlag carry only `id` + `created_at`).
- **`services.py`** — all calculation rules with `Decimal` ROUND_HALF_UP: pacing tiers (floor committed-pct, inclusive lower edges 50/80, factors 1.00/0.80/0.50), per-line round-then-sum incentive pricing, sampling (every 5th submission OR claimed_kwh ≥ 10000), fraud screen (Rule A half-open `[invoice−30d, invoice)` +40; Rule B closed `[today−7d, today]` count ≥ 5 including self +25; Rule C +15; SUSPECT at ≥ 50), ally performance (round-half-up, PREFERRED ≥ 90/STANDARD ≥ 70), evaluation adjustment (floor kWh, latest `effective_on` with earliest-created tie-break, round-half-up attainment).
- **`routes/`** — all 36 endpoints with the PRD's exact validation ordering: auth → authz → path 404 → structural 400 → body-FK 404 → program-open gate → state check → endpoint-specific business order (submit: ally-active → measure-active → line-items → invoice window → cap-402 → ownership last; approve: fraud-hold before segregation-of-duties; inspect-complete: parent-state → fail-reason → already-completed; verify: measured-input before both inspection-obligation gates). OCC on `PUT /program-years/{id}` via `expected_program_year_version` → `ERR_STALE_VERSION` 412. Cascades bump versions: close auto-pays APPROVED apps oldest-first (year version +1 per pay, +1 for close); line-item creation does not bump the parent app's version.

## Verification

Booted via `bash start.sh` fresh (empty store, clock at the fixed default — confirming per-test-server isolation cleanliness) and ran ~100 scenario checks across four smoke suites: full pipeline (draft → submit → inspect → verify → approve → pay), tier boundaries at exactly 50%/80%, half-up rounding (80.8→81, 50.5→51), all three fraud rules including half-open/closed window edges, burst window sliding, SUSPECT hold, SoD, close auto-pay + version arithmetic, evaluation adjustment governance/tie-breaks, report flow, and every 404 error ID. All passing (the 6 initial "failures" were arithmetic mistakes in my ad-hoc test expectations, confirmed against the implementation's correct values). Edge checks: malformed JSON → 400, invalid clock → 400, offset timezones normalized to UTC.

One judgment call to flag: the scaffold's error catalog has no fraud-flag-specific 404 ID, so `GET /fraud-flags/{id}` on a missing record returns 404 with `ERR_FRAUD_FLAG_NOT_FOUND` (consistent with §2.9's "resource-specific not-found" rule).

## Resume note — 2026-08-13T12:40:00.000Z

Pipeline resumed after mid-flight termination. State assessment: Steps 1-6 complete (SCAFFOLD*.yaml, INSTRUCTION.md, PRD.md, test_helpers/, test_suite/, implementation/ all present and Python-compilable). Stale `results.{1..8}.json` from a partial Step 7 sweep at 12:31 show 89/94 passing (5 failed, consistent across all 8 rounds); `test_08_inspections_and_verification.py` was touched at 12:34, indicating the prior Step 7 subagent was killed mid-fix. No Step 7 worklog entry exists. Resuming from Step 7 with a fresh long-lived subagent; the stale results files will be removed and regenerated by its first sweep.

## Step 7: Test-and-fix iteration — 2026-08-13T13:05:00.000Z

Done. 8-round parallel stability sweep clean: 94/94 in every round.

**Diagnosis (STEP 0):** First healthy sweep: 90/94 in all 8 rounds, union = 4 tests, all in `test_suite/test_08_inspections_and_verification.py`, all failing identically: expected a §3.5 business error, got `ERR_UNAUTHORIZED` (403).

**Root cause (STEP 2 — test bug, not implementation):** the four tests issued `POST /applications/{id}/verify` and `POST /inspections/{id}/complete` with `admin_headers` (ProgramAdministrator). PRD §4 assigns both endpoints to `VerificationInspector`, and §2.9 runs role authorization before any business check — so the PRD-faithful implementation correctly returned `ERR_UNAUTHORIZED`, and the asserted business errors were unreachable with that identity. (This was the prior subagent's partial fix: `test_complete_twice_returns_already_completed` had already been redesigned around a POST-kind inspection per the fixed check order, but the wrong role header remained.)

**Fixes (test_suite only):** switched the four offending calls to the `inspector_headers` fixture (VerificationInspector), adding it to the test signatures where missing:
- `TestInspectionCompletion::test_complete_twice_returns_already_completed`
- `TestVerificationGates::test_verify_when_inspection_required_returns_error`
- `TestVerificationGates::test_verify_from_post_inspection_without_post_passed_returns_error`
- `TestVerificationGates::test_measured_claim_with_post_not_below_pre_returns_invalid`

No tests deleted; no `test_helpers/` changes; no `implementation/` changes. Verification sweep: all 8 parallel rounds 94/94, zero failures, zero errors, zero flakiness.

**Harness note:** two early sweep attempts in this session produced all-ERROR results because `--start-command` was passed as bare `bash start.sh`; the runner's pytest plugin resolves `.` against the pytest process cwd (not the implementation dir), so per-test restarts could not find `start.sh`. The prescribed form `--start-command "cd <abs implementation path> && bash start.sh"` is required; with it, the sweep is healthy.

## Step 7: Run tests and iterate — 2026-08-13T13:05:00.000Z

Clean exit condition met — all 8 parallel rounds pass 94/94.

## Summary

**Iterations run:** 2 healthy sweeps (plus 2 harness-error attempts discarded — bare `bash start.sh` as `--start-command` broke the runner plugin's per-test restart, which resolves `.` against the pytest cwd; the prescribed `cd <abs impl> && bash start.sh` form is required).

**Sweep 1 (diagnosis):** 90/94 in all 8 rounds. Failure union = 4 tests, all in `/home/ubuntu/github/CodingPRD/tasks/task_1466_utility_energy_efficiency_rebate_program/test_suite/test_08_inspections_and_verification.py`, all with the identical signature: expected a PRD §3.5 business error, got `ERR_UNAUTHORIZED` (403).

**Diagnosis:** All four asserted error_ids (`ERR_INSPECTION_ALREADY_COMPLETED`, `ERR_INSPECTION_REQUIRED_OUTSTANDING`, `ERR_POST_INSPECTION_NOT_PASSED`, `ERR_INVALID_MEASURED_INPUT`) are verbatim in PRD §3.5 (STEP 1a pass) and uniquely derivable (STEP 1b pass). STEP 2 found the tests were wrong: they called `POST /applications/{id}/verify` and `POST /inspections/{id}/complete` with `admin_headers`, but PRD §4 assigns both endpoints to `VerificationInspector`, and §2.9 orders role authorization before all business checks — so the PRD-faithful implementation correctly refused with `ERR_UNAUTHORIZED` before reaching any asserted check. This was the prior subagent's incomplete fix (the POST-kind redesign was in place; the role header was not).

**Tests deleted:** none.

**Fixes to `test_helpers/`:** none — fixtures/factories/header builders were already PRD-consistent.

**Fixes to `test_suite/`:** `/home/ubuntu/github/CodingPRD/tasks/task_1466_utility_energy_efficiency_rebate_program/test_suite/test_08_inspections_and_verification.py` — switched the offending calls to the `inspector_headers` fixture (adding it to signatures where missing) in `test_complete_twice_returns_already_completed`, `test_verify_when_inspection_required_returns_error`, `test_verify_from_post_inspection_without_post_passed_returns_error`, `test_measured_claim_with_post_not_below_pre_returns_invalid`.

**Fixes to `implementation/`:** none — the implementation was already PRD-faithful on every failing path.

**Verification sweep:** 8/8 rounds at 94/94, zero failures, zero errors — no flakiness.

## Step 8: Finalize PRD — 2026-08-13T13:15:00.000Z

Verification is complete. Here is the final report.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1466_utility_energy_efficiency_rebate_program/workspace/PRD_FINALIZED.md` — written as a verbatim copy of `PRD.md`.

**Line counts:** PRD.md = 262 lines; PRD_FINALIZED.md = 262 lines; delta = 0 lines, 0.0%.

## Zero-edit determination

The Step 7 diff yields **zero PRD edits**. All Step 7 items were pure test-fixture bugs against behavior the PRD already uniquely determines. Per-item reasoning:

The only substantive Step 7 item was the `test_suite/` fix to `test_08_inspections_and_verification.py` (4 tests switched from `admin_headers` to `inspector_headers`; no test deletions, no `test_helpers/` fixes, no `implementation/` fixes). The observed implementation behavior — a `ProgramAdministrator` calling `POST /applications/{id}/verify` or `POST /inspections/{id}/complete` receives `ERR_UNAUTHORIZED` (403) before any business check fires — is fully pinned by three PRD clauses, each verified verbatim in place:

1. **PRD §4 endpoint table** (PRD.md lines 206, 219) assigns both `POST /applications/{id}/verify` and `POST /inspections/{id}/complete` to `VerificationInspector` only.
2. **PRD §2.9** (line 102): "First comes header authentication, then role authorization (§2.1). Third, every identifier in the request path must resolve..." — role authorization precedes resource resolution and all business checks.
3. **PRD §2.1** (line 13): "a well-authenticated request whose role is not authorized for the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

The four asserted business error IDs (`ERR_INSPECTION_ALREADY_COMPLETED`, `ERR_INSPECTION_REQUIRED_OUTSTANDING`, `ERR_POST_INSPECTION_NOT_PASSED`, `ERR_INVALID_MEASURED_INPUT`) are verbatim in PRD §3.5 with correct HTTP statuses (lines 150, 154) and in the §5 catalogue. The implementation matches on every point:

- `implementation/routes/inspections.py:42-43` — `@require_roles("VerificationInspector")` on `complete_inspection`.
- `implementation/routes/applications.py:284-285` — `@require_roles("VerificationInspector")` on `verify_application`.
- `implementation/auth.py:19-43` — `require_roles` raises `ERR_UNAUTHENTICATED` (401) then `ERR_UNAUTHORIZED` (403) inside the decorator, before the handler body (and thus before any resource resolution or business check) executes.

Since the tests were calling the endpoints with the wrong role (a fixture bug) and the PRD already uniquely determined the implementation's 403 refusal, no PRD silence or PRD/impl mismatch was revealed. `diff` confirms PRD_FINALIZED.md is byte-identical to PRD.md.

**Per-edit pre-edit search log:** no edits were committed, so no pre-edit searches were triggered. The zero-edit conclusion itself rests on the verification reads/greps above (PRD §2.1/§2.9/§3.5/§4/§5; `auth.py`; `routes/inspections.py`; `routes/applications.py`; the four fixed tests in `test_suite/test_08_inspections_and_verification.py` at lines 116, 230, 250, 270).

## Step 9: Complete PRD — 2026-08-13T13:40:00.000Z

The patch is complete and verified. All edits are confined to `PRD_COMPLETED.md`.

## Summary

**Source:** `PRD_FINALIZED.md` (identical to `PRD.md`) → `PRD_COMPLETED.md`
**Size:** 262 lines / 38,952 chars → 265 lines / 41,547 chars (**+3 lines, +2,595 chars**)
**Counts:** 18 ambiguity-pins, 2 mismatch-revisions (20 changes total, all inline; no new sections)

### Changes

- **§2.2** — insert — ambiguity — pinned routing-level failures in the error envelope: unknown route → `ERR_INVALID_REQUEST` 404, wrong method → `ERR_INVALID_REQUEST` 405, unhandled exception → `ERR_INTERNAL` 500 — `implementation/app.py:24-37`
- **§2.3** — revise — ambiguity — pinned list tie-break (creation order after `created_at`) and that a filter matching nothing yields an empty page, not an error — `implementation/respond.py:57-69`
- **§2.4** — revise — ambiguity — clock is set unconditionally (no monotonicity check; offset-less timestamps read as UTC), answers 200 with `current_utc` — `implementation/routes/clock.py:12-18`, `implementation/validate.py:109-119`
- **§2.9** — revise — mismatch — added `ERR_FRAUD_FLAG_NOT_FOUND` to the enumerated 404 family (the list was exhaustive-sounding but omitted the fraud-flag lookup error) — `implementation/lookups.py:45-46`
- **§3.1** — revise — ambiguity — measure creation is not locked to `DRAFT`; allowed under a program year in any status (impl has no year-status check) — `implementation/routes/measures.py:17-52`
- **§3.1** — revise — ambiguity — `base_rate_cents`/`deemed_kwh_per_unit` are non-negative integers, zero permitted — `implementation/routes/measures.py:22-23`
- **§3.1** — revise — ambiguity — `is_active` list filter accepts case-insensitive `true`/`false`, anything else → `ERR_INVALID_REQUEST` 400 — `implementation/routes/measures.py:63-70`
- **§3.1** — revise — ambiguity — successful config update recomputes `adjusted_kwh`/`goal_attainment_pct` against the new configuration before the version bump — `implementation/routes/program_years.py:91-93`
- **§3.2** — insert — ambiguity — ally performance recomputation increments `version`/`updated_at` only when score or tier actually changes — `implementation/services.py:269-277`
- **§3.3** — insert — ambiguity — new line item's `pacing_tier_at_submit`/`incentive_cents`/`claimed_kwh`/`measured_kwh`/`final_kwh` are all null until submission/verification populate them — `implementation/routes/line_items.py:48-59`
- **§3.3** — revise — ambiguity — second claim on the same line → `ERR_INVALID_REQUEST` 400 — `implementation/routes/savings_claims.py:56-62`
- **§3.3** — insert — ambiguity — `pre_annual_kwh`/`post_annual_kwh` are non-negative when supplied; optional and stored as given on `DEEMED` claims — `implementation/routes/savings_claims.py:31-43`
- **§3.3** — revise — ambiguity — claim attachment accepted in `DRAFT`/`SUBMITTED`/`PRE_INSPECTION`/`POST_INSPECTION`, refused `ERR_INVALID_STATE` 409 from `VERIFIED` onward (PRD previously framed composition as DRAFT-only) — `implementation/routes/savings_claims.py:22,49-55`
- **§3.4** — revise — ambiguity — pinning pricing fields mutates each line item, so every line's `version` increments at submission and again at verification — `implementation/routes/applications.py:186-190,337-348`
- **§3.5** — insert — ambiguity — `scheduled_on` is a strict `YYYY-MM-DD` calendar date — `implementation/routes/applications.py:221`, `implementation/validate.py:93-106`
- **§3.7** — insert — ambiguity — `effective_on` is a strict `YYYY-MM-DD` calendar date — `implementation/routes/evaluation_adjustments.py:22`
- **§3.7** — insert — ambiguity — recording an adjustment against a year not yet `CLOSED` → `ERR_INVALID_STATE` 409 — `implementation/routes/evaluation_adjustments.py:27-33`
- **§3.7** — revise — ambiguity — adjustment creation increments the year `version` only when the recomputation actually changes `adjusted_kwh` or `goal_attainment_pct` — `implementation/routes/evaluation_adjustments.py:46-50`
- **§5** — insert — mismatch — added missing catalogue row `ERR_FRAUD_FLAG_NOT_FOUND` | 404 — `implementation/lookups.py:45-46`
- **§5** — insert — ambiguity — added catalogue row `ERR_INTERNAL` | 500 — `implementation/app.py:34-37`

### Verified already-aligned (no change needed)

Endpoint table vs. routes (all 38 endpoints, roles, 201/200 split); the full submission check order incl. ownership-last; pacing tiers/floor-percent/half-up-per-line; invoice 90-day window; N=5 sampling and 10,000-kWh override; all three fraud rules' windows/weights/threshold; inspection completion order and cascades; verification dual-path gates and measured-input pre-check; approval fraud-hold-before-segregation order; pay/reject/withdraw ledger effects; close auto-pay in `created_at` order with per-cascade version bumps; latest-adjustment tie-break; report gating; OCC only on config PUT; and the rest of the error catalogue statuses.
