# Worklog — task_1251_bsa_suspicious_activity_reporting_case

## Step 1: Create Task Directory — 2026-08-12T08:37:00.000Z

Task directory pre-assigned by caller: `tasks/task_1251_bsa_suspicious_activity_reporting_case` with `workspace/` subdirectory already created. Step 1 auto-index scan skipped per instructions.

## Step 2: Generate Scaffold — 2026-08-12T09:38:00.000Z

All three scaffold artifacts are written, lint-clean, and verified on disk.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1251_bsa_suspicious_activity_reporting_case/`):
- `SCAFFOLD.yaml` (85 KB) — §1.0–§1.7: preamble, fixed response envelope, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, RBAC. No `scaffold_difficulty_design`/`scaffold_corner_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (94 KB) — single top-level key `scaffold_difficulty_design` (§1.8).
- `SCAFFOLD_CORNER_DESIGN.yaml` (135 KB) — single top-level key `scaffold_corner_design` (§1.9).

**Counts:**
- Entities: **14** (Analyst, Customer, Account, Transaction [immutable, `common_fields: false`], MonitoringScenario, ScenarioThreshold, Alert, Case, SARReport [self-referential `prior_sar_id`], ContinuingReview, LawEnforcementInquiry, InfoShareRequest, AccountDecision, QAReview)
- State machines: **12** (cycles on Case, SARReport, Alert, Account, MonitoringScenario, ContinuingReview)
- Endpoints: **69** (incl. `POST /_clock/set_current_utc` with the mandatory `2026-05-01T00:00:00Z` startup default, and `POST /ops/jobs/daily-compliance-sweep`)
- Errors: **22**; Validations: **21** (priority-ordered); Calculations: **6**; Roles: **4** (segregation-of-duties model; BSAAnalyst/QAReviewer/BSAManager are `entity_backed:Analyst`, ComplianceAdmin opaque); OCC concurrency rules: **2**
- §1.8 instances: **19** — every one of the 9 Difficulty Rules has ≥2 instances; `combinatorial_formula` has 3 covering all three modes (a: SAR filing-deadline branches; b: alert-score nested rounding order, pinned 48 vs naive 47; c: QA quota pool-snapshot order, quota 3 vs wrong-order 2). All numeric asserts were pre-computed by executing the formulas (e.g., tuned/baseline alert scores 48/47, customer risk 550/825, deadlines 2026-05-31 / 2026-06-30 / 2026-09-02, review due 2026-08-03).
- §1.9 instances: **57** total entries (53 with full `test_recipe` chains + 4 `excluded_because` stubs referencing §1.8 instances), spanning all nine claim-extraction sections; every one of the 22 error codes is triggered at least once across §1.8+§1.9.

**Verification:** `scaffold_lint.py` → `VERDICT: clean lint` (854 setup/trigger calls scanned; all calls resolve to §1.5 endpoints, roles, payload schemas, captures, OCC placeholder discipline, and FK reverse-reachability all pass). Instance names are unique across both design files; all stub references resolve; zero forbidden race-vocabulary. Two lint findings during development (FK filter names `subject_customer_id?`) were fixed by renaming the list filters. A pre-existing `worklog.md`/`workspace/` in the task directory (not mine, earlier timestamp) was left untouched.

## Step 3: Copy Shared Files — 2026-08-12T09:39:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1251_bsa_suspicious_activity_reporting_case/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T09:47:00.000Z

**Output**: `workspace/PRD.md` — 46,275 bytes, 297 lines.

### Section List
- §1. Introduction
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim fixed block)
  - 2.3 Pagination
  - 2.4 Resource Identity and Common Properties
  - 2.5 The Logical Clock and the Daily Compliance Sweep
  - 2.6 Customer Risk Rating and the Risk Cascade
  - 2.7 Alert Scoring — Tuned and Baseline Variants
  - 2.8 SAR Filing Deadlines and the Continuing-Review Cadence
  - 2.9 Optimistic Concurrency Control
  - 2.10 Validation Ordering
  - 2.11 Precision and Rounding
- §3. Business Logic & Workflows
  - 3.1 Reference Data: Analysts, Customers, Accounts, and Transactions
  - 3.2 Monitoring Scenarios and the Tuning Lifecycle
  - 3.3 Alert Generation, Triage, and Linking
  - 3.4 Case Investigation and the SAR Decision
  - 3.5 SAR Drafting, QA, Approval, and Filing
  - 3.6 Continuing-Activity Reviews
  - 3.7 Law-Enforcement Inquiries
  - 3.8 314(b) Information Sharing
  - 3.9 Subject Account Decisioning and the Exit Cascade
  - 3.10 Quality Assurance Sampling and the Backlog
- §4. Endpoint Definitions (4-column table, 68 endpoints)
- §5. Error Code Catalogue (2-column table, 22 error IDs)

### Hard Contract Audits

**Contract 1 — Field-Name Coverage: PASS**
- `entities[].fields`: 105 required, 105 present, 0 missing
- `endpoints[].input` / path params: 69 required, 69 present, 0 missing (initial pass missed `to_iso8601`; repaired in §2.5)

**Contract 2 — Rule Coverage: PASS (Zero-Silence audited)**
- 21 priority-ordered `validations[]` entries: all expressed in §2.10 in stated order plus inline at their guarded workflows in §3
- 2 `concurrency_rules[]` OCC entries (`expected_scenario_version` on threshold propose, `expected_sar_version` on narrative edit) plus the in-line `expected_case_version` on `sar-decision`: all expressed with exact `error_id` `ERR_STALE_VERSION` and HTTP 412
- All 14 state machines and every transition (43 transitions across 14 entities): from/to states named, preconditions paired with `error_id`, side effects stated
- 6 `calculations[]` fully transcribed in prose: `scenario_trigger_evaluation`, `alert_risk_score` (TUNED + BASELINE variants, pinned 4-dp component rounding order), `customer_risk_rating_recompute` (STANDARD + ENHANCED, 1.5× multiplier, base 100, 250/150/400 point constants, tier thresholds 200/400/700), `sar_filing_deadline` (30d + 30d extension / 120d continuing), `qa_sample_quota` (0.34 rate, ceil, clamp [1,25], pinned order with the non-conformant subtract-first pattern called out), `backlog_aging_buckets` (0/16/31/61 day edges)
- All 22 `errors[]` referenced at least once in §2 or §3
- All 4 `roles[]` spelled exactly and each `identity:` field translated (opaque for `ComplianceAdmin`; entity-backed `Analyst` for the other three)
- All 37 state enumeration values appear as backticked UPPERCASE tokens (two — `EXECUTED`, `RETIRED` — were initially only implied; repaired in §3.2 and §3.9)
- Sibling-branch symmetry preserved: both `SAR_REQUIRED`/`NO_SAR` decision branches, all three decision types (`EXIT`/`RESTRICT`/`RETAIN`), both continuing-review outcomes, both QA outcomes, all cascade side effects enumerated

**Contract 3 — §3 Path Purity: PASS**
- 456 backtick tokens scanned inside §3; zero begin with `/`, zero are bare HTTP methods, zero are method+path combos. Endpoints referenced only via state-transition framing, role + action verb, or capability description.

## Step 5: Generate Unit Tests — 2026-08-12T10:30:00.000Z

**Files written**

**`test_helpers/` (9 files)** — all PRD-specific infrastructure:
- `types.py` (22 status/type enums + 15 entity TypedDicts; `Transaction` correctly omits `updated_at`/`version` per PRD §2.4), `api_client.py` (69 endpoint methods covering every PRD §4 endpoint), `api_errors.py` (all 22 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity + backlog validators), `factories.py`, `constants.py` (risk/QA/timing constants + 6 narrative fixtures byte-verified against the design YAML recipes), `test_users.py` (opaque ComplianceAdmin constant + mandatory per-instance builders for the three entity-backed roles), `fixtures.py` (`Staff` roster with identity threading, scenario/threshold lifecycle, alert generation, case/SAR state drivers, filed-SAR chain, plus the five heavy composites: `setup_alert_scenario`, `close_cases_no_sar`, `setup_deadline_branch_scenario`, `setup_exit_cascade_scenario`, `setup_risk_cascade_scenario`), `__init__.py` barrel.

**`test_suite/` (13 files)** — `conftest.py` + 12 claim-clustered test files (`test_01_reference_data` … `test_12_authentication`).

**Test count and coverage**
- **92 test functions**, all collected cleanly by `pytest --collect-only`.
- Queue A (Difficulty): **19/19 instances covered, 41 tests** — every instance has ≥2 tests (boundary/deadline/cascade instances have 3).
- Queue B (Corner): **51/52 non-stub instances covered, 51 tests** — exactly one per instance. All 5 `excluded_because:` stubs left untranslated; their difficulty-instance cross-references verified to resolve.

**Skipped instance (1)**
- `Corner/calculations/risk_recompute_365d_window_exclusion` — fails unique derivability. The instance's distinguishing assertion is that a SAR filed exactly 365 days ago drops out of `sar_filings_365d` (exclusive lower bound). PRD §2.6 says only "within the trailing 365 days", and §2.11's boundary rule covers only "at least"/"no more than" phrasing and described half-open intervals — neither applies. A PRD-only reader could legitimately implement an inclusive lower bound and produce score 650 where the instance asserts 400. Skipped per the design-index-only contract; no weakened test or placeholder emitted.

**Verification results (all on disk)**
- `py_compile`: clean over all 22 files in `test_helpers/` and `test_suite/`.
- Design tags: every test function's docstring ends with exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line, copied verbatim from the YAML `name:` and resolving to an existing instance (0 untagged, 0 dual-tagged, 0 dangling, 0 pointing at stubs).
- PRD citations: every quoted citation fragment in all 92 docstrings survives a whitespace-normalized literal grep of `workspace/PRD.md` (0 misses); priority-conflict tests quote the full §2.10 ordering sentence.
- All precomputed numeric assertions cross-checked (tuned 48 vs baseline 47; rounding-order 48; quota clamp→3; deadlines 05-31/06-30/09-02; review due dates 07-30/08-03/08-04; risk 350→600 and 550/825).

## Step 6: Generate Implementation — 2026-08-12T10:30:00.000Z

**Files written** (all under `workspace/implementation/`):
- `start.sh` — reads `$PORT` (default 10000), binds 0.0.0.0, foreground via `exec python3 app.py`, dependency install guarded by `python3 -c "import flask"` so per-test reboots skip pip
- `requirements.txt` (flask), `app.py` (app factory + envelope-shaped 404/405/500 handlers)
- `db.py` (in-memory dict stores + logical clock starting at exactly `2026-05-01T00:00:00Z`; zero seeding — store provably empty at boot, confirmed by smoke tests building all state via the API)
- `util.py` (ids, ISO-8601 3-fractional-digit timestamps, date/datetime parsing, Decimal round-half-up helpers, field validators), `errors.py` (full 22-error catalog), `response.py` (`meta`/`response_type`/`data` envelope, pagination fields in meta), `middleware.py` (X-User-ID/X-User-Role auth, entity-backed role check against Analyst store, clamped limit/offset)
- `services/core.py` — risk recompute (std/enhanced ×1.5 half-up, crossing-INTO-HIGH/PROHIBITED cascade only from a lower band), pinned alert scoring (components rounded to 4dp first, then summed, ×100, rounded), QA quota (ceil(0.34×completions) clamped 1–25, samples never shrink quota), backlog buckets, customer-exit cascade, continuing-review scheduling
- `routes/`: ops, reference, scenarios, alerts, cases, sars, reviews, inquiries, shares, decisions, qa

**Key fidelity decisions**: PRD §2.10 validation priority implemented literally (body-malformed 400 before auth 401; ERR_LE_INQUIRY_OPEN outranks deadline/expiry; ERR_314B_DUPLICATE_WINDOW outranks ERR_CERTIFICATION_EXPIRED; ERR_NO_ACTIVE_THRESHOLD before ERR_SCENARIO_NOT_ACTIVE on evaluate); customer creation sets both risk scores to 100 per PRD (not the formula's 150); Case.version bumps only on the scaffold's explicitly-listed transitions (link-to-case and ON_HOLD transitions refresh `updated_at` only); Transaction carries no `updated_at`/`version`.

**Verification results**:
- `python -m py_compile` over all 19 `.py` files: **OK**
- `bash -n start.sh`: **OK**
- Route-pair diff (throwaway script comparing SCAFFOLD.yaml endpoints vs Flask url_map, converters normalized): **69 declared / 69 implemented, exact match, no missing/extra**
- Live boot smoke tests on fresh processes: full lifecycle passed — scenario/threshold lifecycle with OCC 412 and SoD 403, alert scoring (tuned 87 vs baseline 88 verifying pinned rounding order), evaluate idempotency per (scenario, account, window_end), case assignment capacity/counters, SAR deadline (initial_detection_at + 30d), narrative OCC, filing cascades (filing_reference `SAR-2026-000001`, case→PENDING_QA, RISK_CASCADE restriction, continuing review +90d/+120d), continuing-SAR reopen of CLOSED case, QA quota 422 and duplicate-sample 400, LE-inquiry risk points and PROHIBITED gate on account opening, 314(b) duplicate-window 409 and sweep expiry, EXIT decision cascade (customer→EXITED, draft shares CANCELLED). One bug found and fixed during smoke testing (filing_reference counted the SAR itself → seq off by one).

## Step 7: Run Tests and Iterate — 2026-08-12T10:55:00.000Z

**Iterations run:** 2 sweeps (16 total rounds). Sweep 1: 17 tests failing in all 8/8 rounds (consistent, not flaky). Sweep 2 after fixes: **all 8 rounds pass 92/92**.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — added `assert_same_instant(actual, expected, msg)` (plus `_parse_instant`). Rationale: 14 failing tests asserted exact *strings* (`"...T00:00:00Z"`) for stamped/computed/echoed timestamp fields (`deadline_at`, `due_at`, `filing_deadline_at`, `filed_at`, `sent_at`, `certification_expires_at`, overwritten `effective_to`). PRD §2.4 pins three fractional digits only for `created_at`/`updated_at` (and §2.2 for `api_request_timestamp`); the wire format of these other fields is PRD-silent, while the *instant* is PRD-covered verbatim (§2.8 deadline arithmetic, §3.5 filing stamp, §3.6 review cadence, §3.8 certification +365d). A faithful PRD-only implementer serializing all datetimes with 3 fractional digits (as this implementation does) would fail the string assertion — a unique-derivability collapse on the format aspect only. Per STEP 1c the covered instant assertion was kept (exact parse-and-compare, no approximation) and the uncovered format pin dropped.

**Fixes applied to `test_suite/`:**
- `test_02_scenario_tuning.py::test_threshold_activation_rejected_while_scenario_suspended` — `validate_success()` returns `data`, not `(data, meta)`; the unpack `versions, _meta = current` blew up on the 1-element list. Switched to `validate_paginated()` (STEP 2 test bug).
- `test_02_scenario_tuning.py::test_stale_threshold_proposal_rejected` — the fresh retry's window `[2026-06-01, ∞)` overlapped the first proposal's `[2026-04-01, ∞)`, so the implementation's `ERR_THRESHOLD_WINDOW_OVERLAP` (409) was PRD-correct (§3.2). Gave the first proposal `effective_to="2026-06-01T00:00:00Z"` so the retry is half-open adjacent (explicitly allowed by PRD §3.2) — STEP 2 fixture fix making the test PRD-faithful.
- 19 assertion sites across `test_02` (1), `test_06` (1), `test_07` (12), `test_08` (1), `test_09` (3) converted from `assert x == "<ts>Z"` to `assert_same_instant(x, "<ts>Z")`; imports added in the 5 files.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful everywhere it was failing tests (uniform `.000Z` serialization, correct window-overlap rejection, correct OCC).

## Step 8: Finalize PRD — 2026-08-12T11:05:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one revision.

**Line counts:** PRD.md 297 lines / 46,449 bytes → PRD_FINALIZED.md 297 lines / 47,023 bytes (0% line delta; +1.24% by bytes). One inline revision, no new sections.

**Changes:**
- §2.4 (Resource Identity and Common Properties) — revise — extended the "ISO 8601 UTC with three fractional digits" rule from only `created_at`/`updated_at` to every datetime-valued field the server emits (stamped, echoed, or computed: `posted_at`, `deadline_at`, `filed_at`, `due_at`, `filing_deadline_at`, `sent_at`, `certification_expires_at`, `effective_from`/`effective_to`, alert `window_start`/`window_end`), including caller-supplied values echoed at coarser precision — `implementation/util.py:32-35` (`iso_z`), `implementation/util.py:107-118` (`serialize`).

**Step-7 items requiring no PRD edit:**
- `test_02::test_threshold_activation_rejected_while_scenario_suspended` — pure test bug (`validate_success` unpack); PRD §2.2 already pins the envelope. No edit.
- `test_02::test_stale_threshold_proposal_rejected` — fixture bug; impl's `ERR_THRESHOLD_WINDOW_OVERLAP` on the overlapping retry and acceptance of half-open adjacency are both already pinned verbatim by PRD §3.2 (`routes/scenarios.py:135-141` `_window_overlaps`, status-restricted to `PROPOSED`/`APPROVED` at `routes/scenarios.py:166-177`). No edit.

**Pre-edit search log (edit 1):**
- (a) Subject: wire serialization format of all datetime-valued response fields.
- (b) Paths enumerated and read: `util.py:32-35` (`iso_z` — exactly 3 fractional digits); `util.py:107-118` (`serialize` — every `datetime` → `iso_z`, every `date` → `YYYY-MM-DD`); `response.py:10` (`api_request_timestamp` via `iso_z`, already PRD-pinned in §2.2); `routes/ops.py:22` (clock-set `current_utc` via `iso_z`); grep of all `serialize(` callsites across `routes/{decisions,shares,reviews,alerts,reference,inquiries,cases,scenarios,sars,qa}.py` — every entity response in every endpoint funnels through `serialize`; `routes/scenarios.py:280-378` (evaluate returns only ids/ints, no ad-hoc datetimes; alert `window_start`/`window_end` are datetimes on the serialized entity); `routes/ops.py` sweep and `services/core.py:138-175` backlog return integer counts only; `routes/qa.py:55` `period_month` is a `YYYY-MM` string already pinned by §3.10 (not a datetime — untouched). Echo path confirmed: `req_dt`/`opt_dt` parse caller input to `datetime`, stored raw, re-emitted via `iso_z` (e.g. `effective_from`/`effective_to`, `posted_at`, `certified_at`), so `.000Z` echo of whole-second input is universal.
- (c) Wording adjustment: listed representative field names rather than claiming an exhaustive field list, and scoped the pin to emission format only — deliberately silent on sub-millisecond truncation of caller input (never exercised by Step 7) to avoid a false universal claim. Date-valued fields (`activity_start_date`/`activity_end_date`) were left untouched as out of the Step 7 scope.

## Step 9: Complete PRD — 2026-08-12T11:25:00.000Z

The diff is clean — all edits are in-place line revisions plus one inserted clarifying paragraph in §2.10 (accounting for the +2 line growth; no new sections added). Task complete.

**Source**: `PRD_FINALIZED.md` (297 lines, 47,023 chars) → **`workspace/PRD_COMPLETED.md`** (299 lines, 51,339 chars; +2 lines, +4,316 chars).

**Counts**: 24 ambiguity-pins, 5 mismatch-revisions (29 edit sites total).

### Mismatch revisions
- §2.4 — revise — mismatch — "version increments on every mutation" carved out for `updated_at`-only case touches (alert linking, ON_HOLD entry/exit) — `alerts.py:110`, `inquiries.py:88,127` (`touch(case, bump_version=False)`)
- §2.10 — revise — mismatch — removed duplicate-QA-sample from priority-1 malformed group; reinserted after `ERR_NOT_FOUND`; added missing `ERR_ACCOUNT_NOT_OPEN` after `ERR_INVALID_STATE`; added paragraph pinning endpoint-role-before-lookup but ownership-checks-after-fetch — `qa.py:33-46`, `decisions.py:85-92`, `cases.py:112-115`
- §3.3 — revise — mismatch — evaluation returns a composite `{alert_created, alert_id, aggregate_amount_cents, txn_count}`, not the alert resource, on both fire and no-fire/repeat paths — `scenarios.py:324-339,371-376`
- §3.5 — revise — mismatch — `filing_reference` sequence is one plus the count of SARs already filed in the calendar year (filing order, six-digit zero-pad), not "created_at order" — `sars.py:222-227`
- §4 table — revise — mismatch — scenario fetch carries `current_active_threshold_id`, not an embedded threshold object — `scenarios.py:70-75`

### Ambiguity pins
- §2.2 — insert — ambiguity — unknown path → `ERR_NOT_FOUND` 404; unsupported method → `ERR_INVALID_REQUEST` 405 — `app.py:20-26`
- §2.3 — insert — ambiguity — limit/offset are clamped, not rejected; non-integer → `ERR_INVALID_REQUEST` 400; `created_at` ties broken by insertion order — `middleware.py:46-58`, `util.py:121-122`
- §2.5 — insert — ambiguity — clock-set response carries `current_utc`; sweep summary fields named `alerts_auto_closed`/`reviews_marked_overdue`/`shares_expired` — `ops.py:22,58-62`
- §2.6 — insert — ambiguity — trailing-365-day SAR window is `(now−365d, now]` (strictly after, inclusive now) — `services/core.py:38-42`
- §2.7 — insert — ambiguity — high-risk set matched as ISO alpha-2 codes `IR/KP/CU/SY` against `counterparty_country` — `util.py:10`, `services/core.py:102-103`
- §3.1 — insert — ambiguity — `capacity_max_cases` must be a non-negative integer; duplicate `account_number` → `ERR_INVALID_REQUEST` 400 — `reference.py:30,100-103`
- §3.2 — insert — ambiguity — duplicate `scenario_code` → 400; `stale_alert_days` non-negative; trigger params positive integers; backtest scores required in [0,1] — `scenarios.py:46,49-52,145-147,157-158`
- §3.2 — insert — ambiguity — effective_from-earlier-than-active violation is `ERR_THRESHOLD_WINDOW_OVERLAP` and fires before the scenario-active check — `scenarios.py:258-264`
- §3.4 — insert — ambiguity — case openable regardless of customer status; assign only from `OPEN/ASSIGNED/INVESTIGATING`; same-analyst reassignment → `ERR_INVALID_STATE` — `cases.py:34,87-93`
- §3.4 — insert — ambiguity — start-investigation requires `ASSIGNED`; SAR decision only from `INVESTIGATING`; `decision_rationale` may be empty string — `cases.py:116-118,128,136-138`
- §3.4 — insert — ambiguity — case QA stamps `qa_reviewed_by` on either outcome — `cases.py:186`
- §3.5 — insert — ambiguity — `deadline_at` computed once at creation, never recomputed by edits (incl. `subject_unidentified`) — `sars.py:133-134` (no recompute)
- §3.5 — insert — ambiguity — single-bound window edits validated against the stored other bound — `sars.py:124-128`
- §3.5 — insert — ambiguity — SAR QA `notes` accepted but not persisted — `sars.py:163`
- §3.5 — insert — ambiguity — filing requires `APPROVED` else `ERR_INVALID_STATE` — `sars.py:204-206`
- §3.6 — insert — ambiguity — review completion only from `IN_PROGRESS`; auto-created continuing draft gets empty narrative, `subject_unidentified` false, drafter = completing analyst; case reopen increments assignee's open-case counter — `reviews.py:50-52,63-94`
- §3.7 — insert — ambiguity — inquiry link requires `RECEIVED`; respond requires `UNDER_REVIEW` — `inquiries.py:76-78,102-104`
- §3.8 — insert — ambiguity — future `certified_at` → `ERR_INVALID_REQUEST` 400; record-response only from `SENT`; `response_note` accepted but not persisted — `shares.py:38-40,129-136`
- §3.9 — insert — ambiguity — `RESTRICT` on already-`RESTRICTED` account is a no-op; reversal rationale required but not persisted — `decisions.py:103-107,121`
- §3.10 — insert — ambiguity — `defect_count` is a required non-negative integer — `qa.py:92`
- §3.10 — insert — ambiguity — backlog's open-case total field is named `cases_open` — `services/core.py:174`
- §4 — insert — ambiguity — exact equality-filter fields per list endpoint (alerts/cases/SARs/inquiries/shares/QA reviews) — `alerts.py:26-30`, `cases.py:62-66`, `sars.py:82-85`, `inquiries.py:52-55`, `shares.py:67-70`, `qa.py:72-75`
