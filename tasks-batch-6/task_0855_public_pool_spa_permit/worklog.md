# Worklog — task_0855_public_pool_spa_permit

Scenario: 855. Public Pool & Spa Health Permit: facility permit & classification, water-chemistry & inspection, closure/reopen (fecal/chemical) protocol, lifeguard/attendant & signage, VGB drain-safety compliance, complaint & recreational-water-illness report, plan review, seasonal permit

Difficulty: Expert (passed only to Step 2 scaffold-generator)

## Step 1: Create task directory — 2026-07-26T06:45:47.269Z

Directory pre-assigned by caller: `tasks/task_0855_public_pool_spa_permit` (with `workspace/`). Step 1 index scan SKIPPED per instructions (concurrent pipelines).

## Step 3: Copy shared files — 2026-07-26T06:45:47.269Z

Copied `./INSTRUCTION.md` → `tasks/task_0855_public_pool_spa_permit/workspace/INSTRUCTION.md`. (Run early; independent of Step 2.)

## Step 2: Generate scaffold (Expert) — 2026-07-26T07:39:29.207Z

All three artifacts are written, parse cleanly, and pass `scaffold_lint.py` on the first run.

## What was generated

`/home/ubuntu/github/CodingPRD/tasks/task_0855_public_pool_spa_permit/`
- **SCAFFOLD.yaml** — §1.0–§1.7 plus `conventions:` and `domain_constants:` (no design keys)
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single key `scaffold_difficulty_design`, 9 rule_ids × 2 = 18 instances
- **SCAFFOLD_CORNER_DESIGN.yaml** — single key `scaffold_corner_design`, 83 instances (80 with full recipes, 3 `excluded_because` stubs) across 9 guide sections

## Counts

| Metric | Value |
|---|---|
| Entities | 12 |
| Endpoints | 44 |
| Errors | 50 |
| Roles | 5 |
| State machines | 8 (Inspection declared as two parallel axes) |
| Calculations | 10 |
| Validations | 41 (priority-ordered 1–41) |
| Concurrency rules | 2 (both OCC on a parent `version`) |
| Line counts | SCAFFOLD 2838 · DIFFICULTY 1118 · CORNER 3341 (7297 total) |

## Design shape

Compliance/audit archetype blended with posture-driven gating; **flat** topology, **cyclic** state shape, **segregation_of_duties** role model, immediate consistency. Entities: Operator, Facility, PlanReview, Permit, Inspection, Violation, WaterChemistryReading, ClosureOrder, StaffAssignment, ComplianceArtifact (signage + VGB drain cert), Complaint, FeeLedgerEntry.

Difficulty coverage: dual-variant on two domains (ClosureOrder CT-vs-table remediation window; Complaint single-vs-cluster RWI scoring); combinatorial modes (b) per-component rounding of seasonal proration and (a) nested demerit caps; non-linear machines (Permit ISSUED↔SUSPENDED cycle, Inspection workflow × enforcement parallel axes, ClosureOrder reopen-denial cycle, Violation correct/reject cycle, PlanReview branching); two depth-4 cascades from different triggers; two priority conflicts on different category pairs (state×safety, safety×temporal); boundaries on chlorine ppm and RWI score; cross-entity gates Permit→PlanReview and ClosureOrder→WaterChemistryReading; two overlap semantics (half-open staff shifts vs 60-min buffered closed inspection windows); two conserved quantities (fee-ledger cents, demerit points).

## Notes / decisions worth flagging

- `api_prefix` is `"/"` with flat top-level paths; the lint's FK segment derivation works correctly against it and all 18 FKs have reverse-reachability GETs.
- Every named constant referenced by a rule, formula, or guard has a numeric value in `domain_constants:` (verified programmatically — the only remaining ALL_CAPS tokens are error ids, enum members, and action names).
- Logical clock default pinned at `2026-05-01T00:00:00Z`; `VGB_ENFORCEMENT_START_DATE` is `2026-06-01`, so the VGB gate is deliberately inert by default and must be reached by moving the clock (keeps most setup chains short).
- `ERR_REFUND_NOT_ELIGIBLE` was initially unreachable (terminal REVOKED made the "already refunded" case impossible), so I added `PERMIT_REFUND_WINDOW_DAYS: 30` and re-based the rule on that window; the scaffold, validation row, error condition, and state-machine precondition were all updated together.
- Endpoint count (44) exceeds the §0.4 Expert guideline band of 20–32; 12 entities with CRUD + action surfaces plus the reverse-reachability GETs the lint requires cannot fit under 32, and this matches the size of prior Expert tasks in this repo.

**Orchestrator verification**: all 3 files `yaml.safe_load` OK; endpoint count 44 confirmed.

## Step 4: Generate PRD — 2026-07-26T07:50:39.731Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **445 lines** (orchestrator `wc -l`: 444).

**Structure:** §1 Introduction (3 paras) · §2 Global Specifications with 11 domain-derived subsections (RBAC/identity, verbatim response envelope, pagination, logical clock, common properties & versioning, the 41-step error-precedence ladder, OCC, money & fee ledger, the nine-clause operating-posture gate, cascades/compensation, nested reads) · §3 Business Logic with 9 workflow subsections (operators & classification, plan review, permit application & fee, permit enforcement lifecycle, inspections & scoring, findings & enforcement axis, water chemistry & closure/reopen, staffing/signage/VGB, complaints & RWI) · §4 endpoint table (4 columns) · §5 error table (2 columns).

**Verification (mechanical, run against SCAFFOLD.yaml):**

| Check | Result |
|---|---|
| Endpoint rows in §4 vs scaffold `api_endpoints` | **44 documented / 44 in scaffold** (34 distinct paths / 34) — zero missing, zero extra |
| Distinct error ids vs scaffold `errors[]` | **50 in §5 table / 50 in scaffold**; all 50 also appear in §2/§3 prose with trigger conditions |
| Contract 1 — entity field names | 135 required, 135 present, 0 missing |
| Contract 1 — request-body identifiers | 82 required, 82 present, 0 missing |
| Contract 1 — query params (`limit`, `offset`) | 2 required, 2 present, 0 missing |
| Contract 2 — rule coverage | 2 OCC rules (`expected_facility_version`/`ERR_STALE_FACILITY_VERSION` 412, `expected_plan_review_version`/`ERR_STALE_PLAN_REVIEW_VERSION` 412), 41 validation priorities rendered as an explicit ordered ladder with `applies_to` scopes, all 8 state machines / 9 axes and every transition with preconditions + side effects, all 8 calculations with constants and pinned evaluation order, 4 dual-variant pairs (`FULL_TERM`/`SEASONAL_PRORATED`, `FIXED_TABLE`/`CT_COMPUTED`, `SINGLE_REPORT`/`CLUSTER_AGGREGATE`), both conservation invariants, and the 4-hop FINALIZE cascade |
| Contract 3 — §3 path purity | 851 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP methods, 0 method+path |
| §2.2 verbatim | byte-identical to `section-2.2-response-structure.md` |

**Notes (Step 4):** every declared domain constant carries its numeric value in prose (fee tiers, 25000-gallon free allowance, 2500¢/10k units, 40/20 demerit caps, 85/70 grade thresholds, the full 9-row remediation-minutes table, CT target 15300 / pH 7.5 / ×1.5 / 30-min floor, 1825-day cover lifespan, 720-minute shift cap, RWI weights and the 60-point escalation threshold, `2026-06-01` VGB enforcement date). Boundary inclusivity is pinned explicitly where the scaffold pins it — buffered *closed* inspection windows vs unbuffered *half-open* staff shifts, chlorine/pH strict-boundary classification (0.5 ppm on a pool is `OUT_OF_RANGE`, not `IMMINENT_HAZARD`), and per-component rounding before summing in the seasonal proration. Both withheld design files were not opened.

## Step 5: Generate unit tests — 2026-07-26T08:21:33.988Z

All checks pass. Final state:

```
COMPILE OK (all 21 .py files)          116 tests collected
Difficulty (queue A): 18/18 instances, all with >=2 tests   -> 36 tests
Corner (queue B):     80/80 non-stub instances, all >=1 test -> 80 tests
Stubs: 3/3 excluded_because cross-references resolve       -> 0 tests (correct)
Untagged / dual-tagged / dangling tags: 0
Non-verbatim PRD citations: 0    skip/xfail marks: 0
```

**`test_helpers/`** (9 modules, ~2330 lines)
- `types.py` — 30 enums + 12 entity TypedDicts. `WaterChemistryReading` and `FeeLedgerEntry` correctly omit `updated_at`/`version` (PRD §2.5 append-only).
- `api_client.py` — 44 endpoint methods, one per PRD Section 4 row.
- `api_errors.py` — all 49 error ids + status map, registered with the framework.
- `assertions.py` — per-entity assertions, a `.000Z`-exact timestamp matcher, dashed-UUID matcher, `assert_posture`, `assert_fee_balance_equals_ledger_sum`.
- `fixtures.py` (702 lines) — 7 tiers: primitives, operator+venue, permit lifecycle, plan-review chains (`setup_plan_review_chain(rounds=3)`), inspection lifecycle (`setup_finalized_inspection(findings=[...])`), closure/reopen (`setup_closure_with_pending_reopen`), staffing/signage/complaints.
- `test_users.py` — Operator is the only `entity_backed` role, so `make_operator_headers(operator["id"])` is threaded through every ownership-gated fixture call; the shared constant is used only for non-ownership tests.

**`test_suite/`** — `conftest.py` + 11 test files (116 tests):

| file | tests |
|---|---|
| test_01_operators_and_venues | 14 |
| test_02_plan_review_pipeline | 8 |
| test_03_permit_lifecycle | 15 |
| test_04_permit_fee_assessment | 7 |
| test_05_inspection_scheduling | 9 |
| test_06_inspection_scoring_and_enforcement | 15 |
| test_07_water_chemistry | 7 |
| test_08_closure_reopen_protocol | 13 |
| test_09_staffing_signage_and_drain_safety | 12 |
| test_10_complaints_and_illness_surveillance | 7 |
| test_11_access_control | 9 |

**Skips: zero instances skipped.** Every non-stub instance in both indices passed the PRD-first two-condition filter — this PRD verbatim-states every rule the indices assert, including all boundary pins (§3.7 strict-comparison paragraph), the per-component proration rounding (§3.3, with the 10083-vs-10082 worked example), the 41-rung precedence ladder (§2.6) and both OCC rules (§2.7).

**One design-index assertion deliberately dropped:** `Corner/errors/open_critical_violation_blocks_permit_issuance` asserts `posture_reason == CRITICAL_VIOLATION_OPEN` at a point where the facility's only permit sits in `UNDER_REVIEW`. PRD §2.9 clause 3 ("permit records but none whose status is `ISSUED` -> `CLOSED` / `PERMIT_NOT_ACTIVE`") fires before clause 6, so that sub-assertion contradicts the contract. The instance is still translated and tagged; only that one sub-assert was omitted (the `ERR_OPEN_CRITICAL_VIOLATIONS` error, `open_demerit_points == 10`, and the post-verification success path are all asserted). Design-yaml arithmetic slip, not a PRD gap.

**Verified numerics (recomputed independently, all matched the indices):** `2026-05-01 +364 -> 2027-04-30`; season 06-01..08-31 = 92 d; `round_half_up(30000*92/365)=7562` + `round_half_up(10000*92/365)=2521` = **10083**; `ceil(15300/40)=383` -> `06:23`; `ceil(22950/40)=574` -> `09:34`; `ceil(15300/600)=26 -> floored to 30`; cert `2020-01-01 +1825 -> 2024-12-30`; `2026-05-01 +1825 -> 2031-04-30`; RWI onset gap 10 d (no recency bonus) -> 24+35=59 and 48+35=83; inspection caps 50->40 with uncapped facility total 54.

## Step 6: Generate implementation — 2026-07-26T08:21:33.988Z

`workspace/implementation/` — Python + Flask, 15 modules, no third-party deps beyond Flask:

- `start.sh` — guarded `pip install` (only when `import flask` fails), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000).
- `clock.py` — logical clock (startup default `2026-05-01T00:00:00Z`) + **one shared renderer** `render_datetime` emitting `YYYY-MM-DDTHH:MM:SS.mmmZ` (PRD §2.4 mandates exactly three fractional digits, e.g. `2026-05-01T00:00:00.000Z`, and client-supplied instants echo in that same form). No `datetime.utcnow()` anywhere; the clock-setter endpoint renders through the same function.
- `errors.py`, `response.py`, `validation.py`, `auth.py`, `helpers.py`, `store.py`, `constants.py`, `domain.py`, `serializers.py`
- `routes_core.py`, `routes_plan_permits.py`, `routes_inspections.py`, `routes_ops.py`

**Verification:** `python3 -m py_compile` clean over all 15 `.py` files. Registered Flask routes (method+path pairs, excluding `/static`): **44 — equals the 44 `api_endpoints` in SCAFFOLD.yaml**. `bash start.sh` boots (<4 s), serves smoke requests on `$PORT`, then shuts down cleanly (0 listeners remaining). Fresh boot returns empty collections and `created_at 2026-05-01T00:00:00.000Z`; unknown route -> 404 JSON envelope, bad method -> 405 JSON envelope. No seeding, no `uuid4().hex` (ids are `str(uuid4())`), no wall-clock fallback — grep-verified.

**Behavioural coverage exercised by three end-to-end smoke runs (~90 assertions, all passing):** classification/bather-load/signage derivation, nine-clause posture gate with all reasons, VGB governing-cert + enforcement-date gate, permit ANNUAL/SEASONAL fee (per-component `round_half_up` proration — verified 30000/10000 over 92 days -> 7562+2521=10083), late penalty, ledger conservation (issue -> revoke+refund returns balance to 0), plan-review pipeline incl. OCC, supersede chain, 3-round exhaustion and DISAPPROVE->DENIED cascade, inspection buffered-inclusive conflict vs. staff half-open overlap, scoring/caps/result ladder, 4-hop FINALIZE cascade (fee + notice + permit suspension + posture), VOID compensation, violation OPEN->CORRECTED->OPEN demerit conservation, water classification boundaries (0.5 pool = OUT_OF_RANGE not imminent), auto-closure + suppression, FIXED_TABLE vs CT_COMPUTED (40 ppm @ pH 7.2 -> 383 min; @ pH 7.6 -> 574 min), both four-eyes rules, RWI single vs cluster scoring + escalation closure, and the full error-precedence ladder.

**Interpretive decisions flagged by impl-gen:**
1. `POST /facilities`: ladder step 6 doesn't list `ERR_OPERATOR_NOT_FOUND`, so ownership (`operator_id == X-User-ID` -> `ERR_NOT_RESOURCE_OWNER`) is checked before operator existence.
2. Reopen-request treatment fields: omitting them **resets** them to null, so a re-request without treatment *reverts* to `FIXED_TABLE` — PRD §3.7's literal "stays or reverts to FIXED_TABLE".
3. REINSTATE blocked by an OPEN/REOPEN_REQUESTED closure has no assigned error id in the spec; returns `ERR_INVALID_PERMIT_STATE` (409).
4. Artifact `SUPERSEDED` is fully derived (PRD calls `status` derived), so superseding does *not* bump the older artifact's `version`.
5. `PATCH /facilities` with `is_seasonal: false` and no explicit dates auto-clears the season dates; supplying a non-null date alongside `is_seasonal: false` is `ERR_VALIDATION`.
6. Role-per-action mismatches on multi-actor transition endpoints (e.g. Operator calling `ISSUE`, Inspector calling reopen `VOID`) return `ERR_UNAUTHORIZED` 403.
7. `Connection: close` is set on every response to avoid werkzeug keep-alive races with per-test server restarts.

**Orchestrator verification (Steps 5+6):** 44 `@app.route` decorators in `implementation/`; `py_compile` clean across `implementation/`, `test_helpers/`, `test_suite/`.

## Step 7: Run tests and iterate — 2026-07-26T08:27:12.818Z

**CLEAN PASS on the first sweep. No changes were needed.**

**Iterations run:** 1 (single 8-round sweep, run as 2 waves of 4 via `sweep.sh`; no fix cycle required).

**Tests deleted:** none. No failing test appeared in any round, so STEP 1's PRD-silence / unique-derivability filters were never triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Final per-round results** (`workspace/implementation/results.N.json`):

| round | passed/total |
|---|---|
| 1 | 116/116 |
| 2 | 116/116 |
| 3 | 116/116 |
| 4 | 116/116 |
| 5 | 116/116 |
| 6 | 116/116 |
| 7 | 116/116 |
| 8 | 116/116 |

Every round reports `failed=0, errors=0, skipped=0` (~67 s per round). Verified the count is genuine rather than a collection artifact: 116 uniquely-named `def test_` functions across the 11 files in `test_suite/`, zero `parametrize`, zero `skip`/`xfail` marks, and 116 distinct test names in the results payload.

**Verification of known trap patterns** (a first-sweep clean run warrants extra scrutiny):
- **Timestamp renderer** (recurring impl-gen bug): `grep` for `utcnow|datetime.now|strftime|isoformat` across all 15 implementation modules returns **nothing**. `render_datetime` is defined once at `implementation/clock.py:67` and is the sole formatter for every domain timestamp in `serializers.py`, the envelope in `response.py`, **and** the logical-clock setter endpoint at `routes_core.py:32` — the usual bypass point, correctly routed here.
- **UUID format:** ids are `str(uuid4())` at `store.py:37`; no `uuid4().hex` anywhere.
- **Keep-alive flakiness:** `Connection: close` on every response — why 8 concurrent-wave rounds produced no `RemoteDisconnected` noise.

**Upstream note:** test-gen had already dropped a single design-index sub-assertion that contradicted the PRD (asserted `posture_reason == CRITICAL_VIOLATION_OPEN` while the facility's only permit sat in `UNDER_REVIEW`, but PRD §2.9 clause 3 `PERMIT_NOT_ACTIVE` fires earlier in the ladder). Design-YAML arithmetic slip; the PRD itself is consistent.

**Caveat:** a clean sweep means no test disagrees with the implementation — it does not imply the PRD is complete. Step 9 proceeds unaffected.

**Orchestrator verification:** all 8 `results.N.json` re-read independently — 116/116, failed=0, errors=0. `grep -c "def test_"` over `test_suite/` = 116.

## Step 8: Finalize PRD — SKIPPED — 2026-07-26T08:27:12.818Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the tests exercised, so there is no Step-7 diff to patch against. No `PRD_FINALIZED.md` is produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-07-26T13:15:00.000Z

**NOTE — entry reconstructed during recovery.** The orchestrator `claude -p` process was killed by an account session limit ("You've hit your session limit · resets 11:40am UTC") at the Step 8→9 boundary, after Step 9's subagent had already written `workspace/PRD_COMPLETED.md` but before this worklog entry was appended. No re-run was performed; the on-disk artifact was verified instead.

Verification performed at recovery time:
- `workspace/PRD_COMPLETED.md` present, 95,897 bytes vs `PRD.md` 87,750 bytes (+8,147 B).
- 60 changed lines vs `PRD.md` (full-impl-scan ambiguity pins / mismatch revisions).
- Structurally complete: same 5 `## ` top-level sections as `PRD.md`, same ordering, terminates correctly on the error-catalogue table (`ERR_REFUND_NOT_ELIGIBLE | 409`) — not truncated.
- All 8 `implementation/results.{1..8}.json` re-read: 116/116 passed, 0 failed, 0 errors each. Untouched by recovery.

No files other than this `worklog.md` were modified during recovery.

## Pipeline complete
