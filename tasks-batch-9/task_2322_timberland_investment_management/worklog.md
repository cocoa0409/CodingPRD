# Worklog — task_2322_timberland_investment_management

## Step 1: Create task directory — 2026-09-01T16:12:58.119Z

Created `tasks/task_2322_timberland_investment_management/` and `tasks/task_2322_timberland_investment_management/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T18:07:10.604Z

All three artifacts are complete and lint clean.

## Generated files (task_2322_timberland_investment_management)

- `/home/ubuntu/github/CodingPRD/tasks/task_2322_timberland_investment_management/SCAFFOLD.yaml` (§1.0–§1.7)
- `/home/ubuntu/github/CodingPRD/tasks/task_2322_timberland_investment_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2322_timberland_investment_management/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## SCAFFOLD.yaml counts

13 entities (Fund, Property, Stand, CruisePlot, UnderwritingCase, HarvestBlock, CarbonProject, CarbonDedication, HbuParcel, RecreationalLease, CertificationAudit, AuditFinding, HazardEvent) · 14 state machines · 4 OCC concurrency rules · 11 calculations · 39 ordered validations (priority ladder 10→80) · 57 endpoints · 50 error codes · 7 roles.

Complexity profile: primary archetype `quota_allocation`, secondary `temporal_windowing`; layers optimistic_concurrency + cascading_side_effects + dual_variant_calculation + derived_field_reconciliation; graph topology; cyclic state-machine shape; segregation_of_duties role model; immediate consistency. Logical clock default `2026-08-01T00:00:00Z`.

## §1.8 difficulty design

9 rule_ids × 3 instances = **27 instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant). Also fixed two asserts that referenced a non-existent field (`net_revenue_usd` → `final_net_revenue_usd`).

## §1.9 corner design

**96 instances = 66 full test recipes + 30 `excluded_because` stubs**, across all nine claim-extraction-guide sections: entities 14, state_machines 17, calculations 13, validations 9, endpoints 5, errors 25, rbac 5, cross_cutting_complexity_layers 7, consistency_model 1. Every stub cites an existing §1.8 instance by name; no name collides across the two design files; all 50 error codes are referenced by at least one instance; each of the 4 concurrency rules has its own OCC instance.

## Lint

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    57
  §1.1 entities declared:     13
  §1.8 instances scanned:     27
  §1.9 instances scanned:     66
  Calls scanned (§1.8+§1.9):  1600
```

One lint-driven correction was needed: list endpoints expose `Entity[]` at `$.data`, so pagination-envelope captures (`$.data.total_count`, `$.data.has_more`) were replaced with row captures (`$.data[0].…`) and the envelope values asserted as literals instead. No sibling task directory was read, listed, or grepped at any point.

## Step 3: Copy shared files — 2026-09-01T18:07:27.503Z

Copied `./INSTRUCTION.md` → `tasks/task_2322_timberland_investment_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T18:22:54.654Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2322_timberland_investment_management/workspace/PRD.md`

Structure: §1 Introduction (3 paragraphs) → §2 Global Specifications (2.1 RBAC, 2.2 verbatim response block, 2.3 Pagination, plus 8 domain-named cross-cutting subsections: resource identity/versioning, logical clock & interval conventions, precision/rounding, the stand inventory partition, stale-version guards, reference resolution & validation precedence, segregation of duties, fund cash & derived-field reconciliation) → §3 Business Logic (9 lifecycle-derived subsections) → §4 endpoint table (4 columns) → §5 error catalogue (2 columns). Ends at §5 with no audit footer.

---

### Hard Contract 1 — Field-Name Coverage: **PASS**
- 170 `entities[].fields[].name` identifiers across all 13 entities: **0 missing**, each present verbatim in backticks.
- 161 total candidate identifiers including every `request_body` / `input` / `query_params` / `path_params` key (`current_utc`, `action`, `decision`, `underwriting_case_id`, `expected_stand_version`, `expected_property_version`, `expected_fund_version`, `cure_tons`, `stabilized_noi_usd`, `cap_rate_bps`, `comparable_price_per_acre_usd`, `bare_land_value_per_acre_usd`, `timber_unit_value_usd_per_ton`, `limit`, `offset`): **0 missing**.
- Two passes run. Pass 1 flagged one genuine omission — `certification_audit_id` (AuditFinding) — fixed by naming it in §3.7 as path-derived rather than body-supplied. Pass 2 clean. The only remaining unmatched strings were the 11 `calculations[].name` identifiers and the `provisional`/`final` variant labels, which are internal scaffold identifiers, not fields.
- Also verified: all 52 enum/state literals present; the 31 named constants all present (9 expressed in words/units per the difficulty guideline — e.g. `HAUL_RATE_USD_PER_TON_MILE` 0.145 as "fourteen and one half cents per ton-mile", `WEIGHT_WILDFIRE` 0.45 as "forty-five hundredths", `CARBON_BUFFER_POOL_PCT` 18 as "eighteen percent" — all uniquely recoverable).

### Hard Contract 2 — Rule Coverage: **PASS**
- **Validation priorities**: all 15 precedence ranks reproduced as an explicit ordered list in §2.9, each with its error ID, HTTP status and `applies_to` scope; two worked precedence examples included (stale version beats insufficient tons; duty separation beats state legality).
- **OCC rules**: all 4 concurrency rules in §2.8, each with field, target parent `version`, error, 412, and the scaffold's "why a state check wouldn't catch it" rationale. Explicitly states no other endpoint accepts a version field.
- **Cross-entity side effects**: every `side_effects` entry from all 11 state machines and all 57 endpoints covered — including the SUSPENDED → COMMITTED-block revert (with `harvest_plan_status` and `available_tons` explicitly untouched), sibling-case auto-withdrawal with `decision_note = superseded by approved case`, the two lazy transitions, `replan_property_count` / `valuation_basis_stale_count` maintenance, and the derived-stand mint-then-dispose chain.
- **`applies_to` scopes**: stated for `ERR_FUND_CASH_INSUFFICIENT` (4 endpoints), the three version guards, segregation of duties (3 endpoints), and all 404 body-FK resolution sites.
- **Field-level defaults/types**: all creation defaults spelled out (fund cash seeding and the `harvest_acceleration_required` strict-inequality evaluation at creation; property `PROSPECT`/`NONE`/`ALIGNED`/`CERTIFIED`-or-`UNCERTIFIED`; stand `CRUISE_OPEN` with five 0.00 buckets). CruisePlot's `common_fields: false` stated explicitly — only `id` and `created_at`, no `updated_at`, no `version`.
- **Sibling-branch symmetry**: both branches specified for every forked action — appraisal INVALIDATE (`SUBMITTED`→`NONE` clearing vs `SIGNED`→`STALE` haircut), harvest CANCEL from `RESERVED` vs `COMMITTED`, lease terminate from `ACTIVE` vs `PENDING`, carbon TERMINATE from all four sources, HBU WITHDRAW from all three sources, dedication release from `PENDING`/`ACTIVE`/`REDUCED`, audit CLOSE from `FINDINGS_ISSUED`/`CAR_REVIEW`, `VOIDED` from `RESERVED`/`COMMITTED`.
- **Tail**: all 11 calculations with stepwise rounding order (per-plot 3dp before the mean, mean 3dp before acreage expansion; fee tier keyed on `pre_fee_value_usd` not the post-fee value; unrounded mid-period discount factor; 4dp effective price; nested haul cap and severance floor), all state machines and terminal states, all ~57 endpoint side-effect sets, and the full three-bucket inventory-loss waterfall ordering.

### Hard Contract 3 — §3 Path Purity: **PASS**
Every backticked token in §3 checked programmatically: 0 tokens beginning with `/`, 0 bare HTTP methods, 0 method+path combinations. All §3 operations are referenced by actor + business verb + state pair. Paths and methods appear only in the §4 table (57 rows, exactly matching the scaffold's 57 endpoints, no extras, no omissions).

**Other checks:** §2.2 confirmed byte-verbatim against `section-2.2-response-structure.md`; 50 catalogue rows against 51 scaffold `ERR_*` matches (the 51st, `ERR_XXX`, is the scaffold's response-template placeholder, correctly excluded); 0 status-code mismatches; 0 error IDs used in prose but absent from the catalogue; 0 invented error IDs.

**Isolation:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

One judgement call worth flagging: the scaffold declares a `damaged_tons <= net_merch_tons` precondition on hazard-event creation but assigns it no error ID. The PRD maps it to `ERR_INVALID_REQUEST` so an implementer has a concrete answer.

## Step 5: Generate unit tests — 2026-09-01T20:30:09.675Z

The suite is complete and audit-clean.

## Files written

**`test_helpers/`** (Stage 1, 9 modules): `__init__.py` (barrel), `types.py`, `constants.py`, `api_errors.py` (all 50 error IDs + status map registered via `set_error_http_status_map`), `api_client.py`, `test_users.py` (7 roles + header builders incl. malformed-header variants), `factories.py` (canonical payload builders), `assertions.py` (money/tons/acres/bps tolerances, stand-partition and fund-cash helpers), `fixtures.py` (tract/cruise/appraisal/case/acquisition/harvest/carbon/lease/audit/HBU/hazard builders).

**`test_suite/`** (Stage 2): `conftest.py` + 19 numbered test modules, `test_01`–`test_12` (queue A) and `test_20`–`test_26` (queue B). Final four files added in this pass:
- `test_23_state_machine_paths.py` — 13 tests (11 `state_machines` + the last `endpoints` instance)
- `test_24_rbac_boundaries.py` — 6 tests (5 `rbac`)
- `test_25_validation_rules.py` — 5 tests (4 `validations`)
- `test_26_concurrency_and_versioning.py` — 7 tests (5 `cross_cutting_complexity_layers` + 1 `consistency_model`)

## Counts

- **172 tests, 19 files, 0 audit issues**, all 172 collected by pytest.
- **Queue A (Difficulty)**: 27/27 instances translated, 2–7 tests each (no stubs in that index).
- **Queue B (Corner)**: 66/66 non-stub instances translated, ≥1 test each; the 30 `excluded_because:` stubs emitted zero tests.
- Every docstring carries exactly one verbatim `PRD:` quote (≥8 words, literal-grep verified against `PRD.md`) and terminates in exactly one `Design:` tag resolving to a real non-stub instance. No `skip`/`xfail`, no scaffold references anywhere.

## Instances skipped

None. Every non-stub instance in both indices was translatable under the two-condition filter; the only losses were the 30 pre-marked stubs.

## PRD-first overrides applied where the design YAMLs conflicted with the contract

- `endpoints/audit_close_is_blocked_while_a_finding_remains_open`: asserted **409** (not the design's 422) and posture **`CERTIFIED`** (the design's `COMPLIANT` is not a declared value).
- `rbac/an_acquisition_analyst_cannot_decide_a_case`: property is `UNDER_UNDERWRITING` after submission and `APPROVED_FOR_BID` after approval, not the design's `PROSPECT`.
- `state_machines/audit_suspend_then_reinstate...`: built from **two** open majors, since explicit `SUSPEND` requires `open_major_count` ≥ 2.
- `cross_cutting/a_case_authored_against_a_stale_property_version_is_refused`: asserted the property version **increments** on case creation (§3.2), contradicting the design's static version; all version assertions in the new files are relative (`fresh == stale + 1`) rather than absolute.
- `cross_cutting/an_acquisition_on_a_stale_fund_version_is_refused`: the design's premium had no derivable indices, so the canonical 72/64/48 review was used → composite 66.48, premium 26 570.21, cash 373 429.79 → 273 429.79, NOC −26 570.21, NAV 4 173 429.79.
- `commit_moves_reserved_tons_to_committed...`: relative version bump instead of the design's absolute 3→4.
- NAV of a re-submitted (non-signed) appraisal asserted at cost basis (`acquisition_price_usd`) per §3.3, a figure the design left unstated.

## Step 6: Generate implementation — 2026-09-01T20:30:09.675Z

Implementation complete and verified.

## Files written
Root: `/home/ubuntu/github/CodingPRD/tasks/task_2322_timberland_investment_management/workspace/implementation/`

- `start.sh` (now `chmod +x` — it was non-executable, which broke `./start.sh`; fixed), `requirements.txt` (`flask>=2.2`)
- `app.py` — app factory, `ApiError`/`HTTPException`/`Exception` handlers so every response (including 404 on unrouted paths and 405) uses the envelope; `PORT` env, default 10000, single-threaded, no reloader
- `db.py` (in-memory `Store` over 13 dicts, logical clock pinned to `2026-08-01T00:00:00Z`, id/timestamp/base-field helpers, date arithmetic), `errors.py` (all 50 error ids → status + default messages), `response.py` (envelope, pagination meta, Decimal→JSON), `validate.py` (shape checks → `ERR_INVALID_REQUEST` 400), `middleware.py` (header auth, role and action-granular authz), `calc.py` (all pinned formulas, ROUND_HALF_UP, Decimal prec 50), `serializers.py` (13 field projections, derived buckets injected)
- `services/core.py` — the shared domain engine: partition-identity buckets derived on demand, inventory-loss waterfall, fund cash guard/credit/debit + derived fund recompute, certification-posture recompute, lazy lease expiry and appraisal staleness
- `routes/` — 11 blueprints (`clock`, `funds`, `properties`, `underwriting`, `stands`, `harvest`, `carbon`, `hbu`, `leases`, `certification`, `hazard`) plus `helpers.py`, all mounted under `/timberland`

## Endpoint count
57 non-static rules, matching PRD §4 exactly.

## Verification
- `start.sh` boots a fresh process cleanly; HTTP-checked fund create (201), 404 path resolution, unrouted 404 in-envelope, clock set (200).
- Full in-process end-to-end smoke run passes: clock → fund → property (market-access tier/discount) → stand → 5 cruise plots (+ duplicate → `ERR_DUPLICATE_PLOT_NUMBER`) → cruise-close → underwriting create/submit/decide (+ SoD 403, `ERR_BID_EXCEEDS_UNDERWRITTEN_VALUE` 422) → appraisal SUBMIT/SIGN (signer-vs-case-author SoD 403) → acquire (stale fund version 412, then 200) → investor report → risk review → harvest block (re-entry buffer 409) → lease activate/terminate with prorated + earned/refunded rent, blackout blocking commit (`ERR_LEASE_BLACKOUT_CONFLICT`) → carbon project register (18% buffer pool, permanence end 2066-08-01) → hazard event driving the waterfall (block VOIDED, dedication REDUCED, project REVERSAL_PENDING with deficit 285.52) → salvage settle → `CURE_BUFFER` (insufficient → 422, then cure) → audit with 2 MAJOR findings auto-suspending posture and reverting the committed block → CAR cycle with per-action role gates (403s) and closer≠submitter SoD → audit CLOSED_CONFORMING → HBU list/contract/close with derived DISPOSED stand, exact acreage conservation and `HBU_WITHDRAWAL` waterfall → pagination bounds (limit 0/101 → 400) → 401/403 auth paths.

## Notable design decisions
- Precedence follows PRD §2.9's fixed 15 steps over §3 narrative order (e.g. `ERR_STAND_NOT_INVENTORIED` before `ERR_CERTIFICATION_SUSPENDED`; `ERR_CASE_PROPERTY_MISMATCH` after the 409 domain gates on acquire). Body FKs resolve left-to-right in declaration order; a missing/non-string FK falls through to the 400 shape check.
- On `/audit-findings/{id}/transition`, action-granular authz is evaluated from the raw body action *before* path existence (per §2.1/§2.9 ordering), with unknown actions falling through to the 400 shape check.
- All four claim buckets and `available_tons` are computed on demand from the claiming rows, never stored, so the §2.7 identity cannot drift. HBU close parks tonnage in `hbu_withdrawn_tons` and leaves `net_merch_tons` intact, as §3.9 requires.
- One spec consequence worth flagging: because the waterfall's bucket three only consumes `ACTIVE`/`PENDING` dedications, a shortfall that survives all three buckets is "absorbed implicitly against the withdrawn bucket" (§3.8), which makes `available_tons` legitimately negative in that contrived case. The PRD states no clamp, so the raw identity is preserved.
- Cruise-plot creation bumps `Stand.plot_count` but not the stand `version` (only side effect declared in the scaffold); audit `advance` always bumps the property version exactly once via a per-request dirty-record dedup, even when posture recompute also touches it.

## Step 7: Run tests and iterate — 2026-09-02T04:12:33.000Z

Done. The task was already green; every apparent failure traced to host infrastructure, not to the task.

## Summary

**Iterations run:** 3 verification sweeps (1 aborted official sweep + 2 complete official 8-round sweeps) plus 3 × 8-round sweeps through a contention-filtered local harness. **Zero fix iterations were needed** — no diagnostic STEP 1/2/3 decision was ever reached, because no test ever failed an assertion.

**Tests deleted:** none. No test failed for a PRD-silence or non-unique-derivability reason (or for any reason attributable to the task).

**Fixes to `test_helpers/`:** none.

**Fixes to `implementation/`:** none. Zero files under `test_suite/`, `test_helpers/`, or `workspace/` were modified, created, or deleted (verified by mtime scan; only runner-produced `results.*.json` are new, matching the repo convention of committing them).

### Evidence the task is green
- **Official 8-round sweep, run twice** (`prd-bench-local-run --isolation per-test-server`, 16 rounds × 172 tests = 2752 executions): `failed == 0` in every single round. All 254 + 296 non-passes were `errors`, and 100% of them carry the identical cause — `subprocess.TimeoutExpired` raised inside `prd_bench_local_runner/pytest_plugin.py::_kill_port`. Every one of the 172 tests passed in at least one round in both sweeps.
- **8/8 fully green rounds** (0/172 failed, 1376/1376) through an equivalent harness (fresh server per pytest node, registry-claimed ports) that verifies server identity and retries on host contention.

### Root cause of the official sweep's `errors`
`/home/ubuntu/github/CodingPRD/prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py` restarts the server before every test via
```
subprocess.run(f"pids=$(lsof -ti:{port} -sTCP:LISTEN ...); kill -9 $pids ...", shell=True, timeout=5)
```
`lsof` on this shared host measures **2.2–10.5 s** (sampled every 25 s for 80 min): ~3,200–4,300 processes, ~16,300 TCP sockets, ~120 concurrent `lsof` invocations from ~178 other `prd-bench-local-run` processes, plus ~1,150 zombie `sh` children left by other pipelines' timed-out `_kill_port` calls. Whenever `lsof` exceeds the hard-coded 5 s, `TimeoutExpired` propagates out of `pytest_runtest_setup` and the test is recorded as an `error` before any request is sent. Error rate tracked host load exactly (74% at peak → 15% when quieter), and is independent of the task. This is shared runner infrastructure, so I did not modify it.

Two further host hazards I had to filter out of triage, both also independent of the task: registry-issued ports being bound first by other pipelines (our app then dies on `EADDRINUSE` while the foreign server answers the readiness probe — surfaced as `404 ERR_VALIDATION - No such route.` / `404 ERR_NOT_FOUND - No such resource.`, error IDs absent from this PRD's catalogue), and our server being `kill -9`'d mid-test by another pipeline's `_kill_port` on a recycled port (surfaced as `Connection refused` on the first request).

### Determinism audit (the flakiness surface the 8-round protocol targets)
- Only sort is `db.sorted_records` → `(created_at, _seq)`; no id/UUID tiebreaker, so ties under the pinned logical clock are deterministic.
- `datetime.now()` appears once, for `meta.api_request_timestamp`, which PRD §2.2 line 45 declares server-generated and which no test asserts on. All domain logic uses the logical clock.
- The single `set` is a membership set of `id(rec)` for per-request mutation dedup — no iteration-order dependence.
- Storage remains in-memory dicts only; no seeding, no on-disk persistence.

### Orchestrator's independent re-verification (not the subagent's report)

The orchestrator did not take the above at face value. It re-ran the official 8-round sweep itself and parsed every `results.*.json` directly:

Sweep A (subagent's final, load avg ~197, 308 competing runner processes, 1751 zombies):
```
results.1  passed=130 failed=0 errors=42     results.5  passed=133 failed=0 errors=39
results.2  passed=134 failed=0 errors=38     results.6  passed=144 failed=0 errors=28
results.3  passed=129 failed=0 errors=43     results.7  passed=127 failed=0 errors=45
results.4  passed=146 failed=0 errors=26     results.8  passed=137 failed=0 errors=35
distinct tests 172 · passed in ≥1 round 172 · never passed 0 · errors 296 · non-lsof errors 0
```

Sweep B (orchestrator-run, load avg ~179, 237 competing runner processes — the results on disk):
```
results.1  passed=151 failed=0 errors=21     results.5  passed=150 failed=0 errors=22
results.2  passed=150 failed=0 errors=22     results.6  passed=163 failed=0 errors=9
results.3  passed=157 failed=0 errors=15     results.7  passed=155 failed=0 errors=17
results.4  passed=152 failed=0 errors=20     results.8  passed=149 failed=0 errors=23
distinct tests 172 · passed in ≥1 round 172 · never passed 0 · errors 149 · non-lsof errors 0
```

Independently confirmed: **0 assertion failures in 2752 test executions across 16 rounds**; every one of the 172 tests passed in ≥1 round in *each* sweep; **every** non-pass in both sweeps is `status=error` with `error_message` = `failed on setup with "subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<port> -sTCP:LISTEN ...)' timed out after 5 seconds"` — 0 exceptions, and `duration_seconds` pinned at ~5.03 (the hard timeout), i.e. the error is raised in the runner's own setup hook before any HTTP request reaches the implementation. Orchestrator also measured `lsof -ti:<port>` directly on this host at 1.48 / 3.35 / 3.89 s against the plugin's hard-coded 5 s limit, and observed the error count fall 296 → 149 as load fell 197 → 179 with no code change whatsoever — the dose-response signature of host contention, not of a task defect.

**Step 7 verdict: green.** Exit condition `passed == total` is unreachable on this host purely because of another pipeline's zombie load in shared runner infrastructure that must not be modified; the substantive exit condition — no test failing for any reason attributable to this task — is met with 0/2752 failures. `results.{1..8}.json` from Sweep B are the artifacts on disk.

## Step 8: Finalize PRD — 2026-09-02T04:13:05.000Z

**SKIPPED** per the skill's skip condition. Step 7 exited with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the implementation exhibits at every site the test suite exercised, and there is no `<step_7_diff>` to patch against. No `PRD_FINALIZED.md` is produced; Step 9 sources from `workspace/PRD.md`.

## Step 9: Complete PRD — 2026-09-02T04:26:18.000Z

All planned edits are applied. Verification sweeps: the §4 endpoint table matches the implementation's 57 routes exactly, and the §5 error catalogue matches `errors.py`'s 57 codes and statuses exactly.

## Exit summary

**Source vs output** — `workspace/PRD.md` (no `PRD_FINALIZED.md` present): 437 lines / 92,512 chars → `workspace/PRD_COMPLETED.md`: 438 lines / 105,905 chars (**+1 line, +13,393 chars**). The one added line is a bullet appended to the existing error-envelope bullet list in §2.2; every other change is an in-paragraph insert or revision. No sections added.

**Counts** — 66 changes: **51 ambiguity-pins**, **15 mismatch-revisions**.

### Global specifications
- §2.1 — insert — ambiguity — action-granular authorization outranks path existence, so `action` is read from the body before the path id resolves; an undeclared `action` carries no role restriction — `middleware.py:44`, `routes/certification.py:168`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + 20 random uppercase alphanumerics — `response.py:21`
- §2.2 — revise — ambiguity — `api_request_timestamp` is the one field read from the host wall clock, not the logical clock — `response.py:35`, `db.py:79`
- §2.2 — insert — ambiguity — unroutable paths / unsupported methods answer in the envelope as `ERR_INVALID_REQUEST` with the router's 404/405 — `app.py:29`
- §2.3 — insert — ambiguity — non-integer or out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; empty string treated as absent — `response.py:83`
- §2.3 — insert — ambiguity — `created_at` ties break on server creation sequence — `db.py:102`
- §2.4 — revise — ambiguity — `created_at`/`updated_at` are stamped from the logical clock — `db.py:83`
- §2.4 — insert — ambiguity — the unit of mutation is the request: exactly one `version` bump per resource per request — `services/core.py:23`
- §2.4 — insert — ambiguity — recomputing derived figures on a read is not a mutation; the two lazy status transitions are — `serializers.py`, `services/core.py:230`
- §2.5 — insert — ambiguity — `current_utc` required, any ISO instant normalised to UTC, backwards moves allowed, answers 200 with empty `data` — `routes/clock.py:13`
- §2.7 — insert — ambiguity — the four buckets and `available_tons` are rebuilt from the claiming rows on every serialization — `services/core.py:106`
- §2.11 — insert — ambiguity — recomputing NAV/yield/counters never bumps the fund's `version`; only cash movement does — `services/core.py:249`

### §3.1 Fund / tract / cruise
- §3.1 — insert — ambiguity — `hbu_acres`, `hbu_price_per_acre_usd`, `annual_rec_income_usd` are ≥0 at 2dp and `hbu_acres` is unconstrained by `total_acres` — `routes/properties.py:40`
- §3.1 — revise — **mismatch** — a `NONE`-scheme tract may host audits; they simply can never leave `SCHEDULED` (PRD said it hosts none at all) — `routes/certification.py:42,79`
- §3.1 — insert — **mismatch** — recording a cruise plot raises `plot_count` but does not bump the stand's `version`/`updated_at`; `measured_at` is echoed verbatim — `routes/stands.py:181`

### §3.2 Underwriting
- §3.2 — insert — ambiguity — `bid_price_usd` strictly positive, 2dp — `routes/underwriting.py:53`
- §3.2 — insert — ambiguity — with no contributing stand there is no dominant species and the base tonnage is left ungrown — `calc.py:150`
- §3.2 — revise — ambiguity — both submission state gates fail as `ERR_INVALID_STATE_TRANSITION` — `routes/underwriting.py:95`
- §3.2 — insert — ambiguity — a submission refused on the bid ceiling still retains the freshly recomputed valuation stack — `routes/underwriting.py:102`
- §3.2 — insert — ambiguity — `decision_note` is 1+ chars unbounded; omitting it preserves the existing note — `routes/underwriting.py:123,134`

### §3.3 Appraisal / acquisition
- §3.3 — insert — ambiguity — appraisal input shapes, and present-but-malformed is rank-5 `ERR_INVALID_REQUEST` while absent is rank-13 incompleteness — `routes/properties.py:151,180`
- §3.3 — revise — **mismatch** — `SIGNED`→`STALE` erases nothing (value, methodology, signer, signed-at all retained) — `routes/properties.py:205`
- §3.3 — insert — ambiguity — lazy staling fires only on the property, fund and investor-report reads — `routes/properties.py:95`, `routes/funds.py:53,68`
- §3.3 — revise — **mismatch** — acquisition gate order, including a property-status gate answering `ERR_INVALID_STATE_TRANSITION`, with mismatch after appraisal and cash last — `routes/properties.py:271`

### §3.4 Harvest
- §3.4 — insert — ambiguity — `expected_stumpage_price_usd_per_ton` strictly positive, 2dp — `routes/harvest.py:35`
- §3.4 — revise — ambiguity — the 24-month re-entry advance is calendar months with the day clamped down in short months — `db.py:128`, `routes/harvest.py:57`
- §3.4 — revise — ambiguity — an already-open window yields a negative `years_to_start`, used as-is; the projection is keyed on the stand's own `species_code`/`acres` — `calc.py:161`, `routes/harvest.py:65`
- §3.4 — insert — ambiguity — the property's `version` moves only when `harvest_plan_status` actually changes — `services/core.py:209`
- §3.4 — insert — ambiguity — net revenue is not floored at zero and a negative figure is credited as it stands — `calc.py:227`, `services/core.py:281`
- §3.4 — revise — **mismatch** — commit gates run block-state → stand → certification → blackout (PRD had certification before stand) — `routes/harvest.py:125`
- §3.4 — insert — ambiguity — `actual_tons` and `realized_price_index_factor` both required, ≥0 at 2dp, realized index not confined to 0.10–3.00 — `routes/harvest.py:152`
- §3.4 — revise — **mismatch** — completion evaluates certification *before* the tonnage ceiling — `routes/harvest.py:155`
- §3.4 — insert — ambiguity — a `CANCEL` close ignores any tonnage/price fields — `routes/harvest.py:176`
- §3.4 — insert — ambiguity — suspension-revert bumps each block's `version` but not the stands' — `services/core.py:369`

### §3.5 Carbon
- §3.5 — insert — ambiguity — `dedicated_tons` strictly positive, 2dp — `routes/carbon.py:187`
- §3.5 — revise — **mismatch** — dedication gates run project-open → `STAND_NOT_INVENTORIED` → `STAND_PROPERTY_MISMATCH` — `routes/carbon.py:198`
- §3.5 — revise — **mismatch** — `SUBMIT_VALIDATION` freezes nothing; a `VALIDATION` project still accepts dedications — `routes/carbon.py:108`
- §3.5 — revise — **mismatch** — `cure_tons` ≥0 at 2dp and the cure debits both `cash_balance_usd` and `net_operating_cash_usd` — `routes/carbon.py:101,149`
- §3.5 — revise — **mismatch** — termination from `REVERSAL_PENDING` leaves `buffer_deficit_tons` standing (not zeroed) and sets no `release_reason` — `routes/carbon.py:151,25`
- §3.5 — insert — ambiguity — `PENDING` release on a moved-on project → `ERR_CARBON_PROJECT_NOT_OPEN_FOR_DEDICATION`; `release_reason` 1+ chars, unset when omitted — `routes/carbon.py:237,241`
- §3.5 — insert — ambiguity — releasing an already-`RELEASED` dedication → `ERR_INVALID_STATE_TRANSITION` — `routes/carbon.py:248`

### §3.6 Leasing
- §3.6 — insert — ambiguity — initial `first_year_prorated_rent_usd`/`termination_effective_date` unset, `earned_rent_usd`/`refunded_rent_usd` 0.00, and no property gate at creation — `routes/leases.py:67`
- §3.6 — revise — ambiguity — `termination_effective_date` required and recorded on both branches — `routes/leases.py:118,141`
- §3.6 — insert — **mismatch** — an out-of-window termination date on an `ACTIVE` lease → `ERR_INVALID_STATE_TRANSITION`, not `ERR_LEASE_TERM_INVALID` — `routes/leases.py:123`
- §3.6 — insert — ambiguity — the refund may be negative on a multi-year term and is debited as it stands — `routes/leases.py:127`
- §3.6 — insert — ambiguity — activation and termination do not run the lazy-expiry sweep — `routes/leases.py:84`
- §3.7 — revise — **mismatch** — scheduling checks no enrolment: a `NONE`-scheme tract can carry a `SCHEDULED` audit — `routes/certification.py:42`

### §3.7 Certification
- §3.7 — insert — ambiguity — the three counters are derived on every read; scheduling bumps the property's `version` only if the posture moves — `serializers.py:163`, `services/core.py:394`
- §3.7 — insert — ambiguity — raising a finding leaves the audit's `version` alone and moves the property's only on a posture change — `routes/certification.py:123`
- §3.7 — insert — ambiguity — SUSPEND below two open majors and REINSTATE above one both fail as `ERR_INVALID_STATE_TRANSITION` — `routes/certification.py:86`
- §3.7 — insert — ambiguity — `car_text` 1+ chars with no upper bound — `routes/certification.py:177`
- §3.7 — insert — ambiguity — `VERIFY_CLOSE` imposes no parent-audit state precondition and leaves the audit's `status` untouched — `routes/certification.py:212`

### §3.8 Hazard
- §3.8 — insert — ambiguity — a risk review is permitted at any property `status` — `routes/properties.py:216`
- §3.8 — revise — ambiguity — dominant species for the insect component counts stands of every `status`, including `DISPOSED` derived stands — `services/core.py:308`
- §3.8 — revise — ambiguity — the experience-rated loss ratio is 0.0000 when `insured_value_usd` is 0.00 and is never stored — `calc.py:258`
- §3.8 — revise — **mismatch** — the trailing claim window has a floor and no ceiling, so future-dated events count — `services/core.py:441`
- §3.8 — revise — **mismatch** — the `damaged_tons` ceiling is evaluated *after* the `STAND_NOT_INVENTORIED` gate, not at rank 5 — `routes/hazard.py:41`
- §3.8 — insert — ambiguity — a shortfall surviving all three buckets leaves `available_tons` negative — `services/core.py:112`
- §3.8 — revise — ambiguity — `resulting_status` is the post-cut status, and dedications already `REDUCED` are skipped — `services/core.py:163,199`
- §3.8 — insert — ambiguity — `settled_claim_usd`/`salvage_sold_tons` required, ≥0 at 2dp — `routes/hazard.py:93`
- §3.8 — insert — ambiguity — `salvage_sold_tons` moves no inventory and no cash — `routes/hazard.py:104`

### §3.9 HBU and §4
- §3.9 — insert — ambiguity — identifying a parcel does not mutate the parent stand — `routes/hbu.py:64`
- §3.9 — revise — ambiguity — `closing_costs_usd` ≥0 at 2dp and uncapped, so `net_proceeds_usd` may be negative and reduce both accumulators — `routes/hbu.py:103,150`
- §3.9 — revise — **mismatch** — the derived stand is created already reading `DISPOSED` at `version` 1 (never observable in `INVENTORIED`), inheriting `stand_code`/`species_code`/`age_years`/`site_index`/`mean_net_tons_per_acre`/`cruise_confidence`, with `plot_count` 0, `gross_merch_tons` = `net_merch_tons` = `withdrawn_tons`, and all buckets 0.00 — `routes/hbu.py:166`
- §3.9 — insert — ambiguity — the HBU waterfall keeps no reallocation log — `routes/hbu.py:194`
- §4 — revise — ambiguity — `GET /stands/{id}/hbu-parcels` also returns parcels whose `derived_stand_id` is this stand — `routes/stands.py:116`

### Orchestrator's independent verification of the Step 9 patch

Confirmed structurally minimal and non-destructive, not taken on report alone:
- Section headings byte-identical between `PRD.md` and `PRD_COMPLETED.md` (28 = 28, `diff` empty) — no sections added, renamed or dropped.
- §5 error catalogue holds at exactly **50** `ERR_*` rows in both files — no error codes invented. (The summary's "57 codes" refers to `errors.py`'s internal registry, which includes non-catalogue entries; no new PRD rows were added.)
- Line-level `diff`: **54** lines replaced in place, **55** emitted, i.e. **+1** net line — matching the single appended §2.2 bullet, with every other change an in-paragraph revision.
- File is complete and non-truncated: opens on the `# Timberland Investment Management API` title and closes on the final `| ERR_BUFFER_CURE_INSUFFICIENT | 422 |` catalogue row, exactly as `PRD.md` does.

---

# PIPELINE COMPLETE — task_2322_timberland_investment_management

All nine steps done. `workspace/PRD_COMPLETED.md` is on disk.

| Step | Status | Artifact |
|---|---|---|
| 1 Task directory | done | `tasks/task_2322_timberland_investment_management/` |
| 2 Scaffold | done | `SCAFFOLD.yaml` (2936 L) · `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2894 L, 27 instances) · `SCAFFOLD_CORNER_DESIGN.yaml` (5862 L, 66 recipes + 30 stubs) |
| 3 Shared files | done | `workspace/INSTRUCTION.md` |
| 4 PRD | done | `workspace/PRD.md` (437 L) — 3 hard contracts PASS |
| 5 Unit tests | done | `test_helpers/` (9 modules) · `test_suite/` (19 files, **172 tests**) |
| 6 Implementation | done | `workspace/implementation/` (Python+Flask, 57 endpoints, in-memory only) |
| 7 Test/fix loop | **green** | `results.{1..8}.json` — **0 assertion failures in 2752 executions**, 0 deletions, 0 fixes |
| 8 PRD finalize | skipped | skip condition met (0 deletions, 0 fixes in Step 7) |
| 9 PRD complete | done | `workspace/PRD_COMPLETED.md` (438 L) — 51 ambiguity-pins + 15 mismatch-revisions |

Scenario: **2322. Timberland Investment Management** — 13 entities, 14 state machines, 11 calculations, 39 ordered validations, 57 endpoints, 50 error codes, 7 roles; `quota_allocation` × `temporal_windowing` with optimistic concurrency, cascading side effects, dual-variant calculation and derived-field reconciliation.
