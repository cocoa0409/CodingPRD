# Worklog — task_1110_dust_collection_combustible_dust

## Step 1: Create Task Directory — 2026-08-10T16:48:00.000Z

Pre-assigned output folder `tasks/task_1110_dust_collection_combustible_dust` with `workspace/` subdirectory already existed; Step 1 auto-index scan skipped per instructions. Directory verified present and empty.

## Step 2: Generate Scaffold — 2026-08-10T17:09:00.000Z

## Summary

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1110_dust_collection_combustible_dust/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1110_dust_collection_combustible_dust/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1110_dust_collection_combustible_dust/SCAFFOLD_CORNER_DESIGN.yaml`

**Counts:**
- Entities: **13** (Site, DustSample, Collector, DHA, HousekeepingProgram, HousekeepingAudit, HotWorkPermit, Inspection, InspectionFinding, RetrofitProject, RetrofitLineItem, Incident, CAPAAction)
- State machines: **10** (Collector, DHA, HousekeepingAudit, HotWorkPermit, Inspection, InspectionFinding, RetrofitProject, Incident, CAPAAction, Site-posture)
- Endpoints: **97** (including nested + flat reverse-reachability sub-resources + `/_clock/set_current_utc`)
- Errors: **26**; Roles: **8**; Validations: **28** (priorities 1-28); Calculations: **9**; Concurrency rules: **2** (OCC on Site.version for DHA approve; OCC on RetrofitProject.version for finalize_estimate)
- Difficulty design instances: **18** (2 per each of the 9 difficulty rules — dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant)
- Corner design instances: **32** (one excluded as a stub covered by §1.8)

**Difficulty calibration (harder than expert):**
- Primary archetype **compliance/audit** blended with **posture-driven gating** (Site.posture ∈ {COMPLIANT, CONDITIONAL, DEFICIENT, STOP_WORK} gates commissioning, return-to-service, hot-work start, retrofit execution)
- Role model **segregation_of_duties** (DHA author != approver; incident lead != related hot-work issuer; HK auditor != program creator)
- Dual-variant calculations across **different entity domains**: Kst classification on DustSample (NFPA vs insurer-conservative bands) AND retrofit contingency on RetrofitProject (per-line-then-sum vs sum-then-round rounding)
- Combinatorial formulas in **different modes**: nested rounding on dha_risk_score (mode b) vs min/max + conditional variant branch on explosion_protection_design (mode a)
- Non-linear state machines on **different entities**: DHA revision cycle DRAFT→SUBMITTED→REJECTED→DRAFT, and Incident reopen cycle CLOSED→REOPENED→INVESTIGATING
- Transitive cascades from **different triggers**: DPReading → Collector → DHA → Site (depth-3) and clock-advance → HousekeepingAudit → Site (depth-2)
- Priority conflicts in **different error-category pairs**: state-vs-business_safety (posture_stop_work vs vent_undersized) and intra-business_safety ordering (window_inactive vs permit_overlap)
- Boundary precision on **different metrics/endpoints**: Kst=200 vs 201 band edge on dust-samples, and zero-count/empty-collection hot-work counter invariant
- Resource temporal-overlap in **different interval semantics**: half-open [valid_from, valid_to) pairwise overlap on HotWorkPermit vs aggregate recurrence windows on HousekeepingProgram
- Compensating invariants on **different conserved quantities**: hot_work_in_progress counter under start/close, and open_critical_findings counter under resolve/reopen
- Two OCC concurrency rules via `expected_site_version` and `expected_project_version`

**Lint verdict:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Step 3: Copy Shared Files — 2026-08-10T17:10:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1110_dust_collection_combustible_dust/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T17:20:00.000Z

All structural constraints hold. §4 has 97 endpoint rows + header (the scaffold has 97 endpoints), §5 has 26 error rows + header. Tables have the correct column counts.

## Summary

**Output path**: `/home/ubuntu/github/CodingPRD/tasks/task_1110_dust_collection_combustible_dust/workspace/PRD.md`
**Line count**: 470 lines

### Coverage Audit

**Entities**: 13/13 covered (Site, DustSample, Collector, DHA, HousekeepingProgram, HousekeepingAudit, HotWorkPermit, Inspection, InspectionFinding, RetrofitProject, RetrofitLineItem, Incident, CAPAAction) — every entity has its fields, derived fields, and lifecycle described in §3.

**Endpoints**: 97/97 covered in §4 endpoint table (4 columns: Method, Path, Description, Authorized Roles).

**State machines**: 10/10 covered (Site posture recompute, Collector, DHA, HousekeepingAudit, HotWorkPermit, Inspection, InspectionFinding, RetrofitProject, Incident, CAPAAction). All transitions with their preconditions, side-effects, and target states expressed in §3 narrative.

**Calculations**: 9/9 covered with full formulas in precise business prose — `kst_classify` (with `IC-` insurer-conservative variant), `explosion_protection_design` (with 1.20 performance-based multiplier variant), `dp_trend_derivation`, `housekeeping_schedule`, `dha_kst_rollup`, `dha_risk_score` (with per-dust/per-collector rounding order pinned), `site_posture_derivation` (two-stage with STOP_WORK override), `retrofit_contingency` (per-line-then-sum vs sum-then-round variants), `overdue_housekeeping_counter`. All constants (`Pstat=0.1`, `MIN_PRED=0.05`, `DP_HIGH_ALARM=6.0`, `DP_SLOPE_DELTA=1.5`, `FILTER_MAX_AGE_DAYS=180`, `LOOKBACK=5`, `DUE_SOON_WINDOW_HOURS=24`, all W_* weights, `COMPLIANT_MIN=85`, `CONDITIONAL_MIN=60`, `STOP_WORK_CRITICALS=2`, `RATE_LOW=0.05`, `RATE_MEDIUM=0.12`, `RATE_HIGH=0.22`, `REVIEW_PERIOD_DAYS` reference, `SCORE_CAP=100`) embedded in business prose.

**Validations**: 28/28 priority-ordered rules expressed in §2.10 with explicit ordering and in §3 narratives near each transition. Validation priority chain stated in §2.10 (auth → authorization → existence → state → posture → business-safety → business-constraint → referential → fiscal → OCC → input-shape).

**Errors**: 26/26 error IDs present in §2/§3 narrative with trigger conditions; §5 catalog has 2-column layout (Error ID, HTTP Status Code) with no trigger conditions column.

**Roles**: 8/8 covered (PlatformAdmin, ComplianceManager, ComplianceEngineer, SafetyManager, HotWorkPerformer, HousekeepingAuditor, InspectorUser, IncidentInvestigator) — each named with `identity: opaque` semantics in §2.1, and endpoint authorizations in §4 table.

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 83 required, 83 present, 0 missing
- endpoints[].request_body: 59 required, 59 present, 0 missing
- endpoints[].query_params: 0 required (scaffold defines all inputs via input[] with '?' markers), 0 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 28 checked, 28 expressed in prose (§2.10 enumerates full ordering), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (dha-approve → expected_site_version + ERR_STALE_VERSION/412; retrofit-finalize → expected_project_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 39 checked, 39 fully expressed in §3 narrative with from/to states, preconditions paired with error_ids, and side-effects, 0 missing
- calculations[]: 9 checked, 9 fully expressed in precise business prose with constants embedded, 0 missing
- validations[] conditions: 28 checked, 28 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 97 checked, 97 expressed, 0 missing
- entities[].fields[] structured content: 83 checked, 83 reconstructible from prose (types, defaults, source, initial values), 0 missing
- sibling-branch symmetry: 12 sibling groups checked (DHA approve/reject, collector commission/take-out/return/decommission, finding start/resolve/verify/reopen/dispute/withdraw, retrofit approve/close/cancel, incident start/define/close/reopen, CAPA start/close, posture-gated 4-tuple, housekeeping record/skip, DHA-submit/revise, line-item CRUD, site list/get/patch/recompute, inspection submit/accept/reject), 12 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 513
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Step 5: Generate Unit Tests — 2026-08-10T17:50:00.000Z

Generation complete. Summary follows.

## Files written

**`test_helpers/`** (Stage 1) under `/home/ubuntu/github/CodingPRD/tasks/task_1110_dust_collection_combustible_dust/test_helpers/`:
- `types.py` — 18 status/role enums + 13 entity TypedDicts (all `common_fields: true`; `HousekeepingAudit` uses functional TypedDict syntax because `pass` is a keyword)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (70+ methods incl. `/_clock/set_current_utc`)
- `api_errors.py` — all 26 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_site_posture_invariants` (STOP_WORK override invariant)
- `factories.py` — 14 payload factories, input fields only
- `constants.py` — domain thresholds (Kst bands both variants, DP 6.0/1.5/180d, tier rates, posture bands, 24h/30min permit rules)
- `test_users.py` — `TEST_USERS` for all 8 opaque roles + per-instance `make_<role>_headers(user_id)` builders (needed for SoD/ownership-gated calls: author, approver, performer, auditor, investigator)
- `fixtures.py` — composite setup helpers (site/sample/collector chains, commissioned collectors, submitted DHAs, STOP_WORK sites, estimated retrofit projects, started permits, closed incidents, OCC version readers)
- `__init__.py` — barrel export

**`test_suite/`** (Stage 2) — `conftest.py` + 11 test files: `test_01_sites_and_posture.py`, `test_02_dust_samples_kst_classification.py`, `test_03_collectors_design_and_dp.py`, `test_04_collector_lifecycle.py`, `test_05_dha_workflows.py`, `test_06_housekeeping.py`, `test_07_hot_work_permits.py`, `test_08_inspections_and_findings.py`, `test_09_retrofit_projects.py`, `test_10_incidents_and_capa.py`, `test_11_security_and_rbac.py`.

## Test counts
- **Queue A (Difficulty): 34 tests** — 17 of 18 instances × 2 tests each (≥2 target met for every generated instance).
- **Queue B (Corner): 31 tests** — all 31 non-stub instances × 1 test. The one `excluded_because` stub (`finding_reopen_increments_critical_counter`) was not translated; its cross-reference to `Difficulty/compensating_invariant/critical_finding_counter_invariant_under_resolve_and_reopen` resolves.
- **Total: 65 tests**, all collected by pytest.

## Skipped instances (1)

- **`Difficulty/combinatorial_formula/dha_risk_score_per_dust_then_collector_then_aggregate_rounding`** — fails the PRD-first two-condition filter. Its setup pushes DP readings 3.0/4.0/5.5/6.5; per PRD §3.3 a final reading of 6.5 ≥ 6.0 forces `dp_trend = ALARM_HIGH` (the first branch), so the PRD-derived risk_score is 60.25, not the asserted 58.25 (58.25 corresponds to RISING). The claimed state (`filter_change_due=true` AND `dp_trend=RISING`) is unreachable via uniquely-derivable PRD mechanics: the dp-path always yields ALARM_HIGH, and the 180-day age path depends on the initial value and re-evaluation timing of `last_filter_change_at`, which the PRD never pins. Not weakened, no placeholder — gap stays a gap.

## Judgment calls (documented)
- **`ERR_INVALID_REQUEST`** (invalid-enum test): the error id appears only in the §5 catalogue, but its trigger rule is verbatim PRD prose (§2.10 item 11 "enum values within declared sets" + §3.7's severity enum list), and the catalogue's sole 400 input-shape error makes the mapping uniquely derivable — test kept.
- **`ERR_INVALID_STATE`** for inspection-accept blocking: §3.7 states the precondition, §2.10 item 4 names the error for transition-precondition failures — only plausible mapping.
- Two difficulty recipes had clock-sequencing omissions (permit start attempted outside its window before the intended check could fire); I repaired only the clock choreography, keeping the asserted outcomes verbatim — both outcomes are PRD-derived.
- All difficulty/corner expected literals were numerically verified against PRD formulas (269.776/673.388 vent areas, 1.066 Pred, 12-vs-13 contingency, 251 estimates, 263/264 totals, posture scores 90/100) — all match.

## Lint/stage verdicts
- `py_compile`: all 20 files pass.
- pytest `--collect-only`: 65/65 collected, zero import errors (verified with `API_BASE_URL` set).
- Citation pass: all 108 rule-bearing docstring quotes survive literal grep of `PRD.md` (whitespace-normalized); every test has exactly one terminal `Design:` line resolving to a real instance; no dual/untagged tests.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold"/table references in generated code; no unused imports.
- Coverage audit: queue A 17/18 instances at ≥2 tests (one filtered skip), queue B 31/31 non-stub instances at 1 test, stub cross-reference verified.

## Step 6: Generate Implementation — 2026-08-10T17:50:00.000Z

Clean — only the docstring in db.py mentions "no seeding" (that's a comment, not actual seeding). All source files are pure Python dicts in memory.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1110_dust_collection_combustible_dust/workspace/implementation/`):

- `start.sh` — executable launcher, reads `$PORT` (default 10000), binds 0.0.0.0, guards `pip install` behind a `python3 -c "import flask"` check, `exec python3 app.py` in the foreground
- `requirements.txt` — `flask>=2.3,<4.0`
- `app.py` — Flask app factory, blueprint registration, `ApiError`/404/405/400/500 handlers, `app.run(host="0.0.0.0", port=$PORT)`
- `db.py` — in-memory stores (13 entity dicts + `dha_samples` + `dp_readings`), logical clock defaulting to `2026-05-01T00:00:00Z`, UUID + ISO-8601-with-3-fractional-digit helpers. **Empty at boot; no seeding.**
- `errors.py` — `ApiError` class + all 27 error-ID constants from the catalog
- `response.py` — envelope helpers producing exactly `{meta:{api_request_id, api_request_timestamp}, response_type, data}` and list meta with `limit/offset/total_count/has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, 8-role validation, `require_roles`
- `services/calculations.py` — all 9 calc rules: `kst_classify` (with `IC-` insurer-conservative variant), `explosion_protection_design` (with >25 m³ performance-based 1.20 multiplier, 3-dp half-up), `dp_trend_derivation` (ALARM_HIGH/RISING/STABLE + 180-day filter age), `housekeeping_schedule`, `dha_kst_rollup`, `dha_risk_score` (per-dust/per-collector 2-dp half-up rounding before summation), `site_posture_derivation` (100-base penalties, STOP_WORK override at ≥2 criticals, 85/60 bands), `retrofit_contingency` (per-line-then-sum default, sum-then-round `IC-` variant), `overdue_housekeeping_counter`
- `services/common.py` — body/ISO/enum/number validation, common-field plumbing (`id`/`created_at`/`updated_at`/`version`), pagination (limit default 10, min 1, max 100, offset default 0, created_at-ascending sort), left-to-right path resolution, system auto-transitions on clock advance (audit OVERDUE, permit EXPIRED + auto MINOR finding, CAPA OVERDUE, program posture/DHA overdue refresh), auto-create-finding helper
- `routes/` — 9 blueprints: `sites.py` (incl. `/_clock/set_current_utc`), `dust_samples.py`, `collectors.py` (incl. dp-readings, record_filter_change, commission/take_out/return/decommission), `dhas.py` (link/unlink samples, submit/approve+OCC+supersede/reject/revise), `housekeeping.py` (programs + audits record/skip), `hot_work.py` (issue/start/close/void), `inspections.py` (inspections + full finding lifecycle), `retrofit.py` (projects + line items CRUD + finalize+OCC/approve/start_execution/close/cancel), `incidents.py` (incidents + CAPA actions)

**Endpoint count:** 97/97 scaffold-declared endpoints registered. A diff of Flask's URL map against SCAFFOLD.yaml §1.5 showed `Missing: []`; the single "extra" is Flask's built-in `/static/<path>` route (not part of the API surface).

**Boot check:** Ran `PORT=18711 bash start.sh` from the implementation directory — Flask booted on `0.0.0.0:18711` within ~2 s. Verified live:
- Missing `X-User-Role` → 401 `ERR_UNAUTHENTICATED` with correct error envelope
- `POST /api/sites` (PlatformAdmin) → 201 with correct envelope, site born `CONDITIONAL`, counters 0
- Fresh boot `GET /api/sites` → `total_count=0` (no seeding)
- Kst 250 → `ST2`, `combustible=true`; collector vent design `required=327.128, pred=1.132, a2c=5.0`; commission with undersized vent → `ERR_VENT_UNDERSIZED` 422; after PATCH to 500 m² → `IN_SERVICE`
- DP readings 2.0→6.5 → `dp_trend=ALARM_HIGH`, `filter_change_due=true`; `return_to_service` → `ERR_FILTER_CHANGE_REQUIRED`; `record_filter_change` then return → `IN_SERVICE`
- DHA approve with wrong `expected_site_version` → 412 `ERR_STALE_VERSION`; with correct version → `APPROVED`, `approver_id` set, `review_due_at=+365d`
- Hot-work: start inside window → `IN_PROGRESS`; early close → 422 `ERR_FIRE_WATCH_INCOMPLETE`; clock advance past fire watch → `CLOSED`
- Two CRITICAL findings → `posture=STOP_WORK`, `score=50`
- Housekeeping: never-audited program `OVERDUE`; record past-due audit → `pass=true`, `RECORDED`; future audit record → `ERR_AUDIT_NOT_DUE`
- Retrofit contingency per-line rounding: costs 101/101/103 (LOW/MED/HIGH) → contingency 5+12+23=40, estimated 305, total 345, rounding remainder 0

Orchestrator route-parity check after both steps: scaffold declares 97 (method, path) pairs; Flask URL map registers 97; missing=[], extra=[].

## Step 7: Run Tests and Iterate — 2026-08-10T18:05:00.000Z

All 8 parallel rounds pass 64/64. Clean sweep achieved — exiting per protocol.

## Summary

**Iterations run:** 2 (iteration 1: 63/65 in all 8 rounds with 2 stable failures; iteration 2: 64/64 in all 8 rounds after fixes).

**Tests deleted (1):**
- `test_dp_alarm_raises_dha_risk_score` (`test_suite/test_03_collectors_design_and_dp.py`) — **recompute-trigger silence** (STEP 1b unique-derivability collapse). The test asserted DHA `risk_score` increases after DP readings drive the linked collector to `ALARM_HIGH`. PRD §3.3's DP-reading side-effect list (updates `dp_current_inwc`, refreshes `updated_at`, bumps `Collector.version`, trend derivation, `filter_change_due`) never mentions DHA `risk_score` recomputation, and the only PRD-pinned `risk_score` recompute triggers are §3.4 link/unlink ("each link or unlink triggers recomputation of two derived fields") and §3.2 Kst change. A faithful PRD-only implementation recomputing at exactly those triggers returns the unchanged score (observed: 8.0 → 8.0), while a compute-on-read implementation returns 16.0 — both PRD-consistent. The scaffold rule driving generation was `Difficulty/transitive_cascade/dp_reading_to_alarm_to_collector_filter_due_to_site_posture`, whose claimed depth-2 leg ("Collector's updated derived fields feed dha_risk_score which mutates DHA.risk_score") never made it into PRD prose.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/` (1):**
- `test_window_inactive_beats_overlap_error` (`test_suite/test_07_hot_work_permits.py`) — repaired clock choreography (STEP 2: test was inconsistent with PRD). The old setup advanced the clock past permit B's `valid_to`, which per PRD §3.6 ("when the current clock advances past `valid_to` while the permit is still `ISSUED` ... the system auto-transitions the permit to `EXPIRED`") moved B to `EXPIRED`, so the priority-4 state check correctly returned `ERR_INVALID_STATE` before the priority-6 business-safety rules could run. New choreography: A `[00:00, 08:00)` started `IN_PROGRESS` at 00:00; B `[04:00, 12:00)` attempted at 02:00 — B's window is inactive (not yet opened), B remains `ISSUED` (no auto-expiry), and A's window overlaps B's, so the §2.10 item-6 ordering (`hot-work window active at start` before `no permit overlap`) is what decides: `ERR_PERMIT_WINDOW_INACTIVE`, 422. Assertion unchanged; also removed the now-unused `create_dha_with_linked_sample` import in test_03.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on both failures (stale-but-legal `risk_score` on reading A; correct priority-4-before-6 error ordering on the expired permit).

Orchestrator verification: all 8 results files present on disk, each passed=64 total=64 failed=0.

## Step 8: Finalize PRD — 2026-08-10T18:15:00.000Z

`PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1110_dust_collection_combustible_dust/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts:** PRD.md = 470 lines; PRD_FINALIZED.md = 472 lines (+2 lines, +0.43%). Exactly one paragraph inserted; zero existing prose modified or deleted.

**Changes (one bullet per change):**
- §3.4 — insert — appended a paragraph after the `risk_score` rounding-order sentence pinning the recompute-trigger set for the DHA's two stored derived fields: recomputed only at DHA creation, on link/unlink, and via the §3.2 linked-DustSample update cascade; explicitly noting that DP readings, `dp_trend`/`filter_change_due` changes, collector status transitions, and site-counter changes do not by themselves recompute a DHA's stored `risk_score` — `implementation/routes/dhas.py:65-66,98-99,114-115`; `implementation/routes/dust_samples.py:104-110`; absence of recompute confirmed at `implementation/routes/collectors.py:216-246` (dp-readings, record_filter_change), `:141-213` (status transitions), `implementation/services/common.py:172-244` (clock transitions).

**No edit for the second diff item:** `test_window_inactive_beats_overlap_error` was a pure test-fixture bug. PRD §2.10 already uniquely determines the outcome (priority 4 state-validity before priority 6 business-safety; within item 6, "hot-work window active at start" precedes "no permit overlap"), and `implementation/routes/hot_work.py:120-145` matches it exactly. Keeping the prose verbatim per the method.

**Per-edit pre-edit search log (the single edit):**
- (a) Subject: recompute triggers for DHA stored derived fields `kst_class_highest` and `risk_score`.
- (b) Impl paths enumerated and read/grepped: `routes/dhas.py` (create/link/unlink recompute both fields; approve at `:141` reads the stored `kst_class_highest`; GETs serialize stored values, no compute-on-read); `routes/dust_samples.py:90-110` (PATCH cascade fires on any updatable sample field, recomputing both fields on every linking DHA regardless of DHA status); `routes/collectors.py` (all mutations incl. dp-readings and record_filter_change — no DHA touch); `routes/hot_work.py:147-152,168-172` (counter mutations, no DHA touch); `routes/sites.py:70-107` (site PATCH, recompute_posture, clock endpoint — no DHA touch); `services/common.py:172-244` (`run_system_transitions` refreshes only the separate `overdue` flag on DHAs at `:230-235`); repo-wide grep for `dha_risk_score|dha_kst_rollup|risk_score|kst_class_highest|dha` across all `.py` files confirmed no other call sites.
- (c) Wording adjustments: (1) positive trigger clause says "an update to a linked DustSample triggers the cascade described in §3.2" instead of "Kst change", because the impl fires the cascade on any sample-field update — deferring to §3.2 avoids narrowing it; (2) the negative clause names only `risk_score`, not `kst_class_highest`, since the rollup's inputs change solely through the listed triggers; (3) the sentence is scoped strictly to the two §3.4 derived fields and says nothing about the DHA `overdue` flag, which §3.4.1 correctly pins to clock advance and impl recomputes in `run_system_transitions` — leaving that behavior untouched.

## Step 9: Complete PRD — 2026-08-10T18:20:00.000Z

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1110_dust_collection_combustible_dust/workspace/PRD_COMPLETED.md`

**Size:** PRD_FINALIZED.md 472 lines / 61,827 chars → PRD_COMPLETED.md 478 lines / 68,042 chars (+6 lines, +6,215 chars).

**Counts:** 15 ambiguity-pins, 8 mismatch-revisions (23 change sites total; some edits bundle both).

### Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref)

- §1 Introduction — revise — mismatch — removed the "auditor may not have created the program" SoD claim (impl has no such check anywhere) — `routes/housekeeping.py:171-205`
- §2.1 — revise — ambiguity — pinned that **all eight roles** require a present, non-empty `X-User-ID` — `middleware.py:26-28`
- §2.2 — insert — ambiguity — pinned routing-fallback behaviors: unknown path/unsupported method → `ERR_NOT_FOUND` 404, framework-level bad request → `ERR_INVALID_REQUEST` 400, unhandled server failure → `ERR_INTERNAL` 500 — `app.py:40-57`
- §2.3 — insert — ambiguity — pinned `ERR_INVALID_REQUEST` 400 for non-integer limit/offset, limit outside 1–100, negative offset — `services/common.py:117-130`
- §2.3 — insert — ambiguity — pinned list sort tie-break: `created_at` asc, then `id` asc — `services/common.py:139`
- §2.3 — insert — ambiguity — enumerated all supported exact-match filter query params per list endpoint (impl silently supports them; unrecognized params ignored) — `services/common.py:132-137` + per-route `filters` dicts
- §2.6 — revise — ambiguity — pinned `version` starts at 1 on creation — `services/common.py:89-93`
- §2.8 (×3 edits: intro, item 1, item 2) — revise — mismatch — `expected_site_version` / `expected_project_version` are **optional**; when supplied must be a non-bool integer equal to the parent version (non-integer also → 412); omission skips the OCC check — `routes/dhas.py:145-151`, `routes/retrofit.py:189-195`
- §2.10 — revise — mismatch — reordered validation pipeline to match impl: input shape (required fields, scalar types, enums, ranges, ISO parseability) runs at step 4 right after path existence and **before** body-FK resolution; noted the hot-work-issuance exception where `collector_id` resolves before timestamp parsing; OCC renumbered to step 12 — `services/common.py:42-83`, `routes/hot_work.py:55-70`, `routes/collectors.py:62-70`, `routes/inspections.py:147-156`
- §2.11 — revise — ambiguity — clock capability **sets** the instant verbatim (no monotonicity check; backward sets allowed); response is 200 with `{current_utc}` — `routes/sites.py:96-107`
- §3.1 — insert — ambiguity — new Site born with `posture_score` 100 — `routes/sites.py:41-42`
- §3.1 — revise — ambiguity — site PATCH writes only present non-null fields and bumps version only when something actually changed; changing `insurer_id` does not reclassify existing samples or re-run contingencies — `routes/sites.py:70-84`
- §3.3 — revise — mismatch — commission precondition order corrected to posture gate → vent adequacy → combustibility (§2.10 order), and non-combustible sample pinned to `ERR_INVALID_STATE` 409 (PRD listed vent-first and left the error unpinned) — `routes/collectors.py:145-153`
- §3.3 — insert — ambiguity — DP reading is stored rounded to 2dp round-half-up, that rounded value becomes `dp_current_inwc`, and the 201 response carries the updated Collector object — `routes/collectors.py:224-233`
- §3.3 — insert — ambiguity — after a filter change, `dp_trend` is re-derived from the retained reading window (may remain `RISING` despite `dp_current_inwc` = 0) — `routes/collectors.py:240-245`, `services/calculations.py:101-117`
- §3.3 — insert — ambiguity — auto-created findings carry `due_at` = current clock and start `OPEN`; system-created Inspection gets `inspector_kind=INTERNAL`, `inspector_ref="system"`; target inspection is the most recently created OPEN/SUBMITTED one — `services/common.py:250-282`
- §3.4 — revise — mismatch — DHA link/unlink perform **no state or author check** (any ComplianceEngineer, any DHA status; PRD said "while in DRAFT the author"); both are idempotent on no-op link sets but still recompute and bump version — `routes/dhas.py:88-117`
- §3.4 — insert — ambiguity — DHA submit and revise author-mismatch pinned to `ERR_SOD_VIOLATION` 422 — `routes/dhas.py:126-127, 190-191`
- §3.4.1 — insert — ambiguity — pinned `REVIEW_PERIOD_DAYS` = **365** (PRD never gave the value); approval resets `overdue` to false — `routes/dhas.py:32, 154-157`
- §3.5 — insert — ambiguity — program records `created_by` = acting `X-User-ID` — `routes/housekeeping.py:74`
- §3.5 — revise — mismatch — deleted the "acting auditor must differ from program's creator" SoD rule (impl never evaluates `created_by`); record/skip identity checks (auditor_id equality → `ERR_SOD_VIOLATION` 422) pinned; not-yet-due check applies only on the SCHEDULED path — `routes/housekeeping.py:171-205`
- §3.6 — revise — mismatch — issuance performs **no** `issuer_id` ≠ `performer_id` comparison (PRD said they must differ) — `routes/hot_work.py:50-93`
- §3.6 — insert — ambiguity — start/close/void identity mismatches pinned to `ERR_SOD_VIOLATION` 422; DECOMMISSIONED referenced collector at start pinned to `ERR_INVALID_STATE` 409 — `routes/hot_work.py:124-125, 133-136, 161-162, 182-183`
- §3.7 — revise — ambiguity — inspection acceptance blocked by non-terminal findings → `ERR_INVALID_STATE` 409; rejection cascade decrements `open_critical_findings` only for CRITICAL findings that were **OPEN** (IN_PROGRESS→DISPUTED does not decrement — a stored-counter quirk pinned as-is) — `routes/inspections.py:110-112, 128-135`
- §3.8 — revise — mismatch — at scoping, `trigger_finding_id` need only resolve to an existing finding at the site (no CRITICAL/status requirement until approval) — `routes/retrofit.py:64-70`
- §3.8 — insert — ambiguity — line-item create/update/delete perform no project-status check (allowed in any status) — `routes/retrofit.py:108-170`
- §3.9 — revise — mismatch — CAPA creation requires only IncidentInvestigator role; no incident-status or lead-identity check; creation also bumps the incident's version — `routes/incidents.py:189-214`
- §3.9 — insert — ambiguity — CAPA start/close owner-mismatch → `ERR_SOD_VIOLATION` 422; incident reopen recomputes posture and bumps site version — `routes/incidents.py:234-235, 248-249, 175-185`
- §5 — insert — ambiguity — added `ERR_INTERNAL` | 500 row to the error catalogue — `app.py:52-57`
