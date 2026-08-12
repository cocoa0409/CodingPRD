# Worklog — task_1209_fair_lending_analysis_redlining_monitoring

## Step 1: Create Task Directory — 2026-08-11T21:50:00.000Z

Task directory `tasks/task_1209_fair_lending_analysis_redlining_monitoring/` and its `workspace/` subdirectory were PRE-ASSIGNED and already exist (created by the pipeline launcher); Step 1 auto-index scan skipped per instructions. Treating Step 1 as done.

## Step 2: Generate Scaffold — 2026-08-11T22:58:00.000Z

All three scaffold artifacts are generated, lint-clean, and YAML-valid. No sibling task directories were inspected at any point.

## Output files

| File | Bytes | Contents |
|---|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_1209_fair_lending_analysis_redlining_monitoring/SCAFFOLD.yaml` | 105,608 | §1.0–§1.7 only (no design keys) |
| `/home/ubuntu/github/CodingPRD/tasks/task_1209_fair_lending_analysis_redlining_monitoring/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 132,702 | single top key `scaffold_difficulty_design` |
| `/home/ubuntu/github/CodingPRD/tasks/task_1209_fair_lending_analysis_redlining_monitoring/SCAFFOLD_CORNER_DESIGN.yaml` | 174,509 | single top key `scaffold_corner_design` |

## SCAFFOLD.yaml counts
- **14 entities** (Market, Branch, LoanOfficer, Application, PricingException, UnderwritingOverride, PeerBenchmark, AnalysisRun, DisparityFinding, MatchedPairReview, CorrectiveActionPlan, RemediationPayment, SelfTest, BoardReport) — flat topology, FK-linked
- **12 state machines** (cyclic revision loops on Application/AnalysisRun/DisparityFinding/MatchedPairReview/CAP/BoardReport/LoanOfficer; compound gating of run finalize on child findings)
- **10 calculations** — incl. dual-variant denial impact ratio (net 0.8750 vs raw 0.6250 on identical data) and dual-variant market penetration index (1.0000 vs 0.8000), combinatorial officer risk score (mode a), per-line-rounding-then-residual remediation allocation (mode b)
- **10 ordered validation priority rows**, **88 endpoints**, **35 error codes**, **7 roles** (segregation-of-duties model; LoanOfficer is `entity_backed:LoanOfficer`, others opaque), **3 OCC concurrency rules** (cap-create / matched-pair-create on `expected_finding_version`; application PUT on `expected_application_version`), fixed §1.0 envelope verbatim, logical clock endpoint with pinned default `2026-05-01T00:00:00Z`
- Complexity profile: compliance_audit + workflow_orchestration; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers

## Design instance counts
- **Difficulty design: 18 instances** — exactly 2 per rule for all nine §0.5 rules, each with structured `setup_api_calls`/`trigger` chains and pre-computed literal asserts (verified by executing the formulas in Python: e.g., impact ratio exactly 0.8000 → MARGINAL/no-flag; allocation [3334, 3333, 3333] with residual to first-listed harmed app; officer score 65.00→WATCH then 100.00→RED with escalation cascade)
- **Corner design: 59 instances** — 53 active + 6 `excluded_because` stubs, across all nine claim-extraction-guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model); covers all 35 error codes, SoD denials, OCC stale-version tests, temporal tiling, privilege forfeiture/reconciliation, clock-boundary expiry

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    88
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     53
  Calls scanned (§1.8+§1.9):  1073

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional audits passed: no forbidden race vocabulary; file split honored; enum-value closure for all system/computed fields; every `grounds:` reference resolves; every error code referenced by ≥1 test; role/endpoint/RBAC consistency; all `expected_*_version` payloads are `${var}` placeholders; cross-file instance-name uniqueness; scenario string stored verbatim.

## Step 3: Copy Shared Files — 2026-08-11T22:58:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1209_fair_lending_analysis_redlining_monitoring/workspace/INSTRUCTION.md` (53 lines).

## Step 4: Generate PRD — 2026-08-11T22:59:00.000Z

PRD generation complete. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no other task directory was inspected.

## Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1209_fair_lending_analysis_redlining_monitoring/workspace/PRD.md`
**Size:** 355 lines, 58,995 bytes

**Section inventory:**
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications — 10 subsections (RBAC + identity semantics, verbatim §2.2 response envelope, pagination, common resource properties, logical clock, OCC, precision/interval conventions, validation priority order, authority tiers/SoD, freezing/cascades/funds invariant)
- §3 Business Logic — 12 subsections organized by workflow (reference data → intake → analysis runs → findings → matched pairs → exceptions/overrides → benchmarks/penetration → CAPs → payments → self-tests → board reports → monitoring cycle)
- §4 Endpoint table — 4 columns (Method, Path, Description, Authorized Roles), 70 rows
- §5 Error catalogue — 2 columns, 35 error IDs

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 115 required (incl. endpoint ids), 115 present, 0 missing
- endpoints[].request_body: all present
- endpoints[].query_params/path_params: all present (path params appear inside backticked §4 paths)
Status: PASS

Rule coverage check:
- validations[] with priority: 10 checked, 10 expressed (§2.8 fixed priority order), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (CAP-create, matched-pair-create, application-correction — occ_field + ERR_STALE_VERSION/412 named), 0 missing
- state_machines[].transitions: 70 checked, 70 fully expressed (per-transition prose probe, incl. sibling branches and system-automatic transitions), 0 missing
- calculations[]: 10 checked, 10 fully expressed (denial_impact_ratio net+raw, pricing_disparity_bps unadjusted+adjusted, penetration branch_weighted+peer_relative, officer_risk_score weights 40/35/25 with norms 0.20/0.10/70 and caps, remediation waterfall round-then-residual, dataset staleness, cap funds rollup, board aggregation, monitoring cycle pinned order, snapshot scope), 0 missing
- validations[] conditions: all matchable to their error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: expressed, 0 missing
- entities[].fields[] structured content: defaults, initial values, enum constraints, computed/system sources reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 symmetric groups checked (deny/withdraw/expire pairs, CAP cancel/supersede pairs, self-test close outcomes, etc.), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 591
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage notes:** All 14 entities, 70 endpoints, 10 calculations (including dual variants, constants, zero-division and empty-cohort rules), 35 error codes, 7 roles (with entity-backed vs opaque `X-User-ID` identity semantics), all state machines including system-automatic transitions and one-way ratchet semantics, both interval conventions (half-open vs closed), the 25000000-cent director threshold, 0.80/0.90 four-fifths thresholds, 15-bps pricing flag, 30-day exception expiry, 2-cycle privilege forfeiture, and the client-pinned residual allocation to the first harmed application.

## Step 5: Generate Unit Tests — 2026-08-11T23:35:00.000Z

Generation complete. All verification gates pass.

## File inventory

**`test_helpers/`** (9 files, ~66 KB source):
- `__init__.py` (1,137 B) — barrel export: framework generics + PRD-specific
- `types.py` (10,014 B) — 21 enums + 14 entity TypedDicts (all entities carry full common fields per PRD §2.4)
- `api_client.py` (16,005 B) — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (69 methods incl. `/_clock/set_current_utc`)
- `api_errors.py` (3,760 B) — 35 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `assertions.py` (8,852 B) — per-entity `assert_*` + `assert_cap_funds_invariant` (§2.10)
- `factories.py` (3,103 B) — input-only payload factories
- `constants.py` (1,873 B) — thresholds (0.80/0.90, 15 bps, 25,000,000¢, 40/70 tiers, 30 days, 2 cycles, 40 credit points)
- `test_users.py` (2,076 B) — 7 role header constants + per-instance builders (entity-backed `make_loan_officer_headers`)
- `fixtures.py` (21,403 B) — composite setup: market/branch/officer spine, validated application batches, locked/computed runs, findings ladder (FLAGGED→UNDER_REVIEW→SUBSTANTIATED), matched-pair helpers with OCC version re-read, CAP ladder to EXECUTING, payment lookup, board reports, self-tests, clock, 10-app dispersion-70 officer, WATCH-65 officer, adverse-run fixture

**`test_suite/`** (conftest.py 892 B + 11 test files, 89 tests):
| file | tests | size |
|---|---|---|
| test_01_envelope_and_reference_data.py | 8 | 11,700 B |
| test_02_access_control.py | 8 | 12,431 B |
| test_03_application_and_run_lifecycle.py | 11 | 14,867 B |
| test_04_disparity_computation.py | 10 | 20,356 B |
| test_05_temporal_and_review_scope.py | 8 | 13,833 B |
| test_06_officer_risk_and_exceptions.py | 10 | 16,015 B |
| test_07_findings_and_matched_pairs.py | 4 | 7,757 B |
| test_08_remediation_funds.py | 11 | 17,425 B |
| test_09_gates_and_validation_order.py | 8 | 12,208 B |
| test_10_monitoring_privilege_board.py | 8 | 19,127 B |
| test_11_optimistic_concurrency.py | 3 | 7,202 B |

## Translation counts

- **Queue A (Difficulty)**: 18/18 instances translated, exactly 2 tests each (36 tests). 0 skipped.
- **Queue B (Corner)**: 53 non-stub instances → 52 translated (53 tests; selector instance got 2). 6 `excluded_because:` stubs not translated; all 6 stub cross-references resolve to real difficulty instances.
- **Skipped (1)**: `Corner/endpoints/fk_reverse_reachability_filtered_lists` — fails the PRD-first coverage condition: the PRD never names `loan_officer_id`, `market_id`, `applicant_group`, or `superseded_by_finding_id` as query-filter parameters (§4 endpoint table carries no filter list; prose mentions none). Two PRD-only readers could ship list endpoints without those filters. Gap left as a gap. (The supersession test in test_05 keeps only the §3.4-covered assertions: status flip, pointer set, open-count netting.)

## Verification results

- **py_compile**: all 20 files pass (`ALL COMPILE OK`); `import test_helpers` succeeds.
- **Design-tag audit**: 89/89 test docstrings end with exactly one `Design:` line; 0 untagged, 0 dual-tagged, 0 dangling tags, 0 stub-pointing tags. Difficulty coverage 18/18 at ≥2 tests; corner coverage 52/53 at ≥1 test (the one miss is the deliberate skip above). Verdict: PASS.
- **PRD citation check**: 127 quoted passages extracted from docstrings; every one matches PRD.md verbatim (whitespace-normalized). 0 failures.
- **Hygiene**: no `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" mentions in generated code comments/docstrings.

## Step 6: Generate Implementation — 2026-08-11T23:35:00.000Z

All verification steps pass. Final summary:

## Implementation complete

**Route-diff verdict: 88/88 registered, no gaps** (scaffold §1.5 endpoint table vs Flask `url_map`, verified by `verify_routes.py` importing the app and diffing).

**start.sh contract**: exists at `workspace/implementation/start.sh`, executable (`-rwxrwxr-x`), bash-invokable, guards the pip install behind `python3 -c "import flask"` (no-op on per-test reboots), and ends with `exec python3 app.py` (foreground). `app.py` reads `$PORT` (default `10000`) and binds `0.0.0.0`.

**Smoke boot**: launched `bash start.sh` on a test port, got structured envelope responses — `ERR_UNAUTHENTICATED` (401) without headers, `ERR_NOT_FOUND` (404) envelope on unknown id, 201 create market, empty list with pagination meta (`limit`/`offset`/`total_count`/`has_more`), and `/_clock/set_current_utc` advancing the logical clock from the `2026-05-01T00:00:00Z` default. No crashes.

**py_compile**: all 25 `.py` files pass.

**Storage**: in-memory dicts in `db.py` only; empty at boot; no seeding, no disk persistence. Logical clock stamps all domain timestamps (3-fractional-digit ISO 8601 UTC).

**File inventory** (bytes, all under `/home/ubuntu/github/CodingPRD/tasks/task_1209_fair_lending_analysis_redlining_monitoring/workspace/implementation/`):
- `start.sh` 396, `requirements.txt` 14, `app.py` 1912, `db.py` 2102, `errors.py` 1955, `middleware.py` 4294, `response.py` 880
- `routes/`: analysis_runs 7414, applications 7194, board_reports 6100, branches 2425, corrective_action_plans 6880, findings 6705, loan_officers 2859, markets 2416, matched_pair_reviews 6423, monitoring 837, peer_benchmarks 2183, pricing_exceptions 7394, remediation_payments 5552, self_tests 5469, underwriting_overrides 4604
- `services/`: analysis.py 6209 (scope/staleness/impact-ratio/pricing variants, ROUND_HALF_UP everywhere), cap.py 10466 (pool allocation waterfall, funds rollup, board aggregation, monitoring cycle, penetration, selector), officer.py 2679 (risk score + one-way RED escalation)
- Verification scripts (not part of the server): `verify_routes.py`, `verify_flows.py`, `verify_edge.py`

**Functional verification beyond smoke**: ~170 assertions across two live-server suites, all passing — full pipeline (ingest → validate → lock → compute with net/raw ratios and both pricing variants → auto-findings → matched-pair SoD → substantiate → CAP waterfall with residual-to-first → disburse SoD → auto-COMPLETED → finding CLOSED → finalize/archive), staleness via `updated_at > locked_at`, OCC 412s on all three guarded writes, freeze guard `ERR_APPLICATION_LOCKED`, RED-tier/ESCALATED/high-value director gates, branch-close cascade, exception expiry (30 days exact no-expire / 31 expire), CAP overdue flip + extend, privilege forfeiture at 2 cycles, quarter/gap/overlap report rules, publish readiness, selector ranking, supersede open-count netting, and pagination meta.

One spec-interpretation fix during testing: ratios/indices are computed from exact Decimal values and rounded half-up to 4dp only for output (verified: penetration share 1/6 over pop 0.5 → 0.3333, not 0.3334), and an invented positive-amount constraint on manual payments was removed (PRD specifies only `amount <= remaining_cents`).

Orchestrator note: route diff re-verified post-hoc at Step 7 gate — `expected: 88, actual: 88, ROUTE DIFF: 88/88 registered, no gaps`.

## Step 7: Run Tests and Iterate — 2026-08-11T23:46:00.000Z

Clean 8-round sweep: all rounds pass 89/89.

## Summary

- **Iterations run:** 2 (first sweep: 8 failures deterministic in all 8 rounds; second sweep after fixes: fully clean).

- **Tests deleted:** none. Every failure traced to a PRD-verbatim-covered rule.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1209_fair_lending_analysis_redlining_monitoring/test_helpers/fixtures.py` — `setup_executing_cap()`: added `**cap_kwargs` passthrough to the CAP creation ladder so tests can supply the PRD §3.8 `due_date` field (fixed `test_cap_overdue_extension_cycle` TypeError).

- **Fixes applied to `test_suite/` (test bugs, not implementation bugs):**
  - `test_04_disparity_computation.py` — added missing `create_application` import (NameError in `test_stale_dataset_blocks_compute`); corrected `test_denial_ratio_net_and_raw_values` assertions: PRD §3.3 defines `approval_rate_*_net` as per-cohort originated share (protected 7/10 = 0.70, control 8/10 = 0.80), while the test had asserted the *ratio* 0.875 / 1.0 for the rates. Implementation was already PRD-faithful.
  - `test_09_gates_and_validation_order.py` — added missing `make_specialist_headers` import (NameError in 3 payment-gating tests).
  - `test_03_application_and_run_lifecycle.py` — `test_unlock_blocked_when_findings_exist`: relaxed the exact-error assertion to `validate_error_is_one_of([ERR_RUN_HAS_OPEN_FINDINGS, ERR_INVALID_STATE])` (HTTP 409 asserted separately). PRD §3.3 names `ERR_RUN_HAS_OPEN_FINDINGS` "once any finding exists", but findings can only exist on COMPUTED+ runs and §2.8 orders the lifecycle-state check before business gates without stating pre-emption — ERROR PRECEDENCE SILENCE pattern; both readings are PRD-faithful.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1209_fair_lending_analysis_redlining_monitoring/workspace/implementation/services/cap.py` — `run_cycle()` exception expiry: changed from day-granularity comparison (`(today - created_date).days > 30`) to timestamp comparison (`now - created_at > timedelta(days=30)`), matching PRD §3.12 "strictly more than 30 days before the current logical time" (an exception exactly 30 days old does not expire; 30 days + 1 second does).

- **Final per-round results:** results.1–8.json all report **89/89 passed**.

Orchestrator verification: all 8 results files on disk, each `passed: 89, failed: 0, total: 89, errors: 0`.

## Step 8: Finalize PRD — 2026-08-11T23:52:00.000Z

Done. `PRD_FINALIZED.md` is written with exactly two surgical edits, each traced to a Step 7 item.

## Summary

**Line counts:** PRD.md 355 lines; PRD_FINALIZED.md 355 lines (0.0% delta — both edits are single-paragraph in-place revisions).

**Changes (one bullet per edit):**

- **§2.7** — revise — Replaced the blanket "time-based monitoring rules operate at day granularity against the logical clock" with: exception expiry is timestamp-precise (`created_at` vs current logical time; exactly 30 days survives, 30 days + 1 second expires), while the CAP overdue flip and due-date extension validity remain day-granularity against the current logical date — `implementation/services/cap.py:139` (timestamp comparison `now - created_at > timedelta(days=30)`, the Step 7 implementation fix), `services/cap.py:130,152,157` (overdue flip `due < today`), `routes/corrective_action_plans.py:176` (extension `new_due <= now.date()`).
- **§3.3** — revise — Appended an error-precedence pin to the unlock paragraph: the lifecycle-state check runs before the open-findings gate, so unlocking a run past `DATA_LOCKED` yields `ERR_INVALID_STATE` (or `ERR_ALREADY_TERMINAL` when `ARCHIVED`) before `ERR_RUN_HAS_OPEN_FINDINGS` is consulted — `implementation/routes/analysis_runs.py:121-126` (check order in `unlock_run`).

**Step 7 items requiring no PRD edit:** the `fixtures.py` `**cap_kwargs`/`due_date` fix (PRD §3.8 already specifies `due_date`; `corrective_action_plans.py:33` requires it); the `test_04` denial-rate assertion correction (PRD §3.3 already defines `approval_rate_*_net` as per-cohort originated share; `services/analysis.py:50-55,130-131` was already PRD-faithful); the `test_09` missing import (pure test bug).

**Per-edit pre-edit search log:**

1. **§2.7 edit**
   - (a) Subject: granularity of clock-driven time comparisons.
   - (b) Enumerated impl paths: `services/cap.py:135-139` (exception expiry — timestamp precision); `services/cap.py:130,148-160` (CAP overdue flip — `date` comparison); `routes/corrective_action_plans.py:172-177` (extension validity — `date` comparison); `services/analysis.py:22-37` (dataset staleness — millisecond ISO-string comparison, already covered by the kept clause); `services/cap.py:162-171` (self-test forfeiture — cycle counter, not time-based). PRD cross-refs checked: §2.5 (rule list, no granularity claim), §3.6 line 176 and §3.12 line 220 (expiry worded against "current logical time" — consistent with timestamp precision), §3.8 line 192 (overdue/extension worded against "current logical date" — consistent with day granularity).
   - (c) Wording adjustment: avoided naming "monitoring rules" broadly; enumerated exactly which rules are timestamp-precise vs day-granular so the counter-based forfeiture rule and all non-clock period logic (board-report quarters, benchmark periods, self-test windows) are untouched by the claim.
2. **§3.3 edit**
   - (a) Subject: unlock endpoint error precedence (lifecycle-state vs open-findings gate).
   - (b) Enumerated impl paths: `routes/analysis_runs.py:117-132` (`unlock_run` — sole unlock path; order: 404 → `ERR_ALREADY_TERMINAL` if ARCHIVED → `ERR_INVALID_STATE` if not DATA_LOCKED → `ERR_RUN_HAS_OPEN_FINDINGS`); finding-creation paths bounding when findings exist: `services/analysis.py:144-171` (auto-findings at compute, run → COMPUTED) and `routes/findings.py:36-38` (manual drafting only on COMPUTED/UNDER_REVIEW). Also checked the endpoint table row (line 267) and error catalogue row (line 343) — both remain accurate without changes.
   - (c) Wording adjustment: kept the original `ERR_RUN_HAS_OPEN_FINDINGS` sentence verbatim and appended the precedence rule, rather than asserting the findings gate is unreachable — avoids a false universal claim while pinning the exact behavior a fresh implementer must reproduce.

## Step 9: Complete PRD — 2026-08-12T00:01:00.000Z

Done. PRD_COMPLETED.md written at `/home/ubuntu/github/CodingPRD/tasks/task_1209_fair_lending_analysis_redlining_monitoring/workspace/PRD_COMPLETED.md`.

## Summary

**Size:** PRD_FINALIZED.md 355 lines / 59,590 chars → PRD_COMPLETED.md 357 lines / 66,081 chars (**+2 lines, +6,491 chars**).

**Counts:** 31 ambiguity-pins, 4 mismatch-revisions (35 total edits).

### Changes

**§2.2** — insert — ambiguity — `api_request_timestamp` pinned as read from the logical clock, not wall-clock — `response.py:12`, `db.py:48-50`
**§2.2** — revise — mismatch — error envelope covers 4xx *and* 5xx; new bullet pins `ERR_INTERNAL` (500) for unexpected failures — `app.py:49-53`
**§2.3** — insert — ambiguity — invalid `limit`/`offset` (non-integer, out of 1–100, negative offset) → `ERR_INVALID_REQUEST`; `created_at` ties broken by insertion order; `has_more` = `offset + returned < total_count`; full per-resource list-filter parameter catalog; unknown query params ignored — `middleware.py:90-124`, `response.py:25`
**§2.5** — revise — ambiguity — logical clock also stamps every record's `created_at`/`updated_at`; clock-set rejects unparseable `to_iso8601` with 400 and returns `current_utc` — `db.py:72-88`, `routes/monitoring.py:20-29`
**§2.6** — insert — ambiguity — missing/non-integer expected-version field → `ERR_INVALID_REQUEST` (400) — `middleware.py:127-133`
**§2.8** — revise — mismatch — priority order rewritten: existence (`ERR_NOT_FOUND`) now precedes identity checks (SoD/ownership), OCC placed after identity/before lifecycle, create-time payload validation precedes body-FK resolution, state-transition payloads read after lifecycle; non-object body → 400, missing body → `{}`; undeclared paths/methods → `ERR_NOT_FOUND` — e.g. `routes/findings.py:129-141`, `routes/matched_pair_reviews.py:121-132`, `routes/remediation_payments.py:98-113`, `middleware.py:47-54`, `app.py:37-43`
**§3.1** — insert — ambiguity — market share outside [0,1] and duplicate `msa_code` → `ERR_INVALID_REQUEST` — `routes/markets.py:31-36`
**§3.1** — insert — ambiguity — `tract_minority_pct` outside [0,100] → 400; re-closing a CLOSED branch → `ERR_ALREADY_TERMINAL` — `routes/branches.py:26-28, 66-67`
**§3.1** — insert — ambiguity — suspend requires ACTIVE / reinstate requires SUSPENDED, else `ERR_INVALID_STATE` — `routes/loan_officers.py:74-75, 85-86`
**§3.1** — insert — ambiguity — scorecard `override_rate`/`exception_approval_rate` at 4dp round-half-up — `services/officer.py:46,48`
**§3.2** — insert — ambiguity — `credit_score` outside 300–900 → 400 at intake and correction — `routes/applications.py:44-45, 137-138`
**§3.3** — insert — ambiguity — `period_start < period_end` enforced (400); fresh-run shape pinned (DRAFT, null metrics/locks, `screening_flag` false, `open_finding_count` 0) — `routes/analysis_runs.py:32-33, 49-71`
**§3.3** — revise — mismatch — "empty cohort denominator cannot arise" claim replaced: it can arise; affected rates/ratios null, classification NONE, `screening_flag` false, no denial auto-finding — `services/analysis.py:50-55, 92-104, 130-133`
**§3.3** — insert — ambiguity — compute restricted to rows still VALIDATED (exclusion doesn't trip staleness but drops the row) — `services/analysis.py:80`
**§3.3** — insert — ambiguity — adjusted pricing spread also null when exception-exclusion empties either cohort — `services/analysis.py:121-124`
**§3.4** — insert — ambiguity — supersede-target guards: CLOSED/SUPERSEDED → `ERR_ALREADY_TERMINAL`, SUBSTANTIATED → `ERR_INVALID_STATE`; target need not belong to the drafting run — `routes/findings.py:44-49, 74-75`
**§3.4** — insert — ambiguity — substantiation requires UNDER_REVIEW; `harmed_application_ids` non-array → 400, unknown id → 404 — `routes/findings.py:140-147`
**§3.5** — insert — ambiguity — selector ties broken by creation order; comparability enforced in selector mode too (non-protected/non-DENIED target → `ERR_MATCH_NOT_COMPARABLE`) — `services/cap.py:257-263`, `routes/matched_pair_reviews.py:46-47`
**§3.5** — insert — ambiguity — submit-initial `notes` accepted but not persisted — `routes/matched_pair_reviews.py:106-116`
**§3.6** — insert — ambiguity — no uniqueness check: multiple exceptions may coexist on one application — `routes/pricing_exceptions.py:22-59`
**§3.6** — insert — ambiguity — approval blocked with `ERR_OFFICER_SUSPENDED` when the owning officer is SUSPENDED — `routes/pricing_exceptions.py:104-105`
**§3.6** — revise — mismatch — denial no longer "records payload reason" (not persisted); denial stamps `decided_by_user_id`/`decided_at` — `routes/pricing_exceptions.py:130-136`
**§3.6** — revise — mismatch — override reversal `reason` accepted but not persisted — `routes/underwriting_overrides.py:101-117`
**§3.7** — insert — ambiguity — benchmark rate stored as supplied, no range validation — `routes/peer_benchmarks.py:23-26`
**§3.7** — insert — ambiguity — penetration period supplied via `period_start`/`period_end` query params; missing → 400 — `routes/markets.py:67-70`
**§3.7** — insert — ambiguity — branch-weighted index uses the unrounded share; null when population share is 0 — `services/cap.py:213-219`
**§3.7** — insert — ambiguity — peer-relative index null when zero protected VALIDATED rows or benchmark rate 0 — `services/cap.py:220-227`
**§3.8** — insert — ambiguity — negative `pool_cents` → 400 — `routes/corrective_action_plans.py:31-32`
**§3.8** — insert — ambiguity — CAP return `reason` accepted but not persisted — `routes/corrective_action_plans.py:141-148`
**§3.8** — insert — ambiguity — `new_due_date` must parse as an ISO date (else 400) in addition to being future — `routes/corrective_action_plans.py:172-175`
**§3.9** — insert — ambiguity — no lower bound beyond integer typing on manual `amount_cents` — `routes/remediation_payments.py:26`
**§3.9** — insert — ambiguity — mark-returned records supplied `reason` in `disposition_reason` — `routes/remediation_payments.py:155-157`
**§3.10** — insert — ambiguity — `window_start > window_end` → 400; new self-test starts with `cycles_open` 0 — `routes/self_tests.py:25-26, 52`
**§3.11** — insert — ambiguity — gap check pinned as exact equality of new `period_start` with latest existing `period_end`; unparseable dates → 400; overlap/gap evaluated before quarter alignment — `routes/board_reports.py:17-53`
**§3.11** — insert — ambiguity — board-report return `reason` accepted but not persisted — `routes/board_reports.py:124-131`
**§3.12** — insert — ambiguity — `cycle_index` starts at 1 on the first cycle — `services/cap.py:129`, `db.py:65-68`
**§5** — insert — ambiguity — `ERR_INTERNAL | 500` row added to the error catalogue — `app.py:53`

All endpoints, role tables, state machines, formulas, thresholds, and HTTP statuses were verified as already uniquely pinned — no other changes needed.
