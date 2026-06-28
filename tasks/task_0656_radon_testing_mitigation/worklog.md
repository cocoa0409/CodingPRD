# Worklog — task_0656_radon_testing_mitigation

## Step 1: Create Task Directory — 2026-06-26T14:44:47.500Z

Pre-assigned folder used as-is: `tasks/task_0656_radon_testing_mitigation`. Folder and `workspace/` subdir already existed (auto-index scan pre-done). No index computation performed.

## Step 2: Generate Scaffold — 2026-06-26T15:11:00.000Z

All three scaffold artifacts written, well-formed, key-split correctly, clean lint verdict.

**Structural counts (Expert-tier calibration):**
- **Entities: 10** — Property, Inspector, MitigationCrew, RadonTest, MitigationJob, Permit, Warranty, RetestSchedule, PaymentRecord, ClockState (target 10–15) ✓
- **Endpoints: 38** — flat topology (`api_prefix: ""`); each FK child has single-resource GET + filtered-list GET for reverse-reachability, plus full workflow action surface (above 20–32 guideline due to flat topology's mandatory reverse-reachability GETs)
- **Error codes: 28** (target 18–30) ✓
- **Calculations: 6, all with variants** (target 3+): radon_result_average, action_level_classification, mitigation_quote, warranty_refund, payment_ledger_balance, next_retest_due ✓
- **State machines: 6** — RadonTest, MitigationJob, Permit, Warranty, RetestSchedule, Property
  - **Cycles:** MitigationJob (RETEST_PENDING→REWORK→SCHEDULED re-mitigation loop); RetestSchedule (ARMED→ARMED recurring self-loop)
  - **Parallel dimensions:** Warranty (coverage_status × claim_status evolve independently)
  - **Compound:** Property posture derived from child RadonTest/MitigationJob states
- **Concurrency rules: 2** — OCC on Property.version (schedule); OCC on Warranty.version (cancel)

**Difficulty design:** 9 rule_ids × 2 instances = 18 instances. **Corner design:** 9 sections, 29 active instances + 5 `excluded_because` stubs.

**Key mechanics:** dual-variant radon averaging (valid-hours vs all-hours mean diverges across 4.0 pCi/L action level: 3.5 vs 4.0); inclusive 4.0 boundary; tiered+rush mitigation quote with pinned evaluation order; conservation invariants on net cash and covered-price; transitive depth-3 cascade (record-result → job CLEARED → Warranty issued → RetestSchedule armed).

**Lint:** `scaffold_lint.py` → clean lint (539 calls scanned). All §1.8/§1.9 calls conform to §1.5; all §1.1 FKs have reverse-reachability in §1.5.

## Step 3: Copy Shared Files — 2026-06-26T15:11:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0656_radon_testing_mitigation/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T15:17:00.000Z

PRD written to `workspace/PRD.md` (267 lines), ending at §5 Error Code Catalogue, no audit footer.

**Sections covered:** §1 Introduction (3 paras); §2 Global Specs (9 subsections: RBAC all 6 roles, §2.2 response structure verbatim, pagination, common resource properties, nested reference resolution & validation ordering, compound posture/cascades/derived-field reconciliation, OCC both rules + 412 error IDs, monetary precision integer cents half-up + pCi/L 1 decimal, uniqueness); §3 Business Logic (8 subsections scattering all fields/formulas/thresholds/transitions); §4 Endpoint Definitions (all 38 endpoints, 4-column); §5 Error Code Catalogue (all 28 codes, 2-column).

**Hard Contract checks:** Field coverage PASS (69/69 fields, 39/39 params); Rule coverage PASS (validations ordering, 2 OCC rules, all state machine transitions w/ preconditions+error_ids+side-effects, all 6 calculations w/ formulas+constants, sibling-branch symmetry equal density); Path purity PASS (380 backtick tokens, 0 paths/methods in §3). §2.2 matches source byte-for-byte.

**Confirmation:** Did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 5: Generate Unit Tests — 2026-06-26T15:23:00.000Z

(launched concurrently with Step 6)

Generated complete test infrastructure for task_0656.

**test_helpers/ — 9 files:** types.py (entity TypedDicts + status/role enums; PaymentRecord carries only id/created_at), api_client.py (one method per endpoint), api_errors.py (27-error ApiErrorId enum + HTTP-status map registered with framework), assertions.py, factories.py, constants.py (quote/refund/action-level literals), test_users.py (opaque-role constants + per-instance builders for the 3 entity-backed roles: Inspector→Inspector.id, CrewLead→MitigationCrew.id, ClientContact→Property.id, identity threaded through ownership-gated fixtures), fixtures.py (composite lifecycle helpers setup_actionable_property → setup_quoted_job → setup_scheduled_job → setup_installed_job → setup_cleared_job_with_warranty, handling logical-clock advance + multi-entity clear cascade), __init__.py.

**test_suite/ — conftest + 8 test files, 65 tests total.**
- **Queue A (Difficulty): 36 tests** — all 18 difficulty instances × 2 tests each (dual-variant calc, combinatorial quote, non-linear state machine, transitive cascade, priority-pair conflict, boundary precision, cross-entity state dependency, resource temporal overlap, compensating invariant)
- **Queue B (Corner): 29 tests** — all 29 non-stub corner instances × 1 test each

**Audit (all clean):** every docstring ends with exactly one Design: tag; all 47 distinct tags resolve to real instance names; 5 excluded_because corner stubs NOT translated; NO instances skipped (all had verbatim PRD coverage + unique derivability); no skip/skipif/xfail; no scaffold/Table/§ references; all PRD citations survive literal grep; pytest --collect-only collects 65 tests, no import errors.

## Step 6: Generate Implementation — 2026-06-26T15:28:00.000Z

(launched concurrently with Step 5)

**NOTE:** The Step 6 subagent terminated with a terminal API error after 41 tool uses, BEFORE returning its summary. Orchestrator verified the implementation was fully written prior to the crash:
- **Source files (20, ~2244 lines):** app.py, db.py, errors.py, middleware.py, response.py, requirements.txt, start.sh; routes/ (admin, properties, radon_tests, mitigation_jobs, payment_records, permits, warranties, retest_schedules); services/ (calc, domain, jobs_cascade, listing, validate).
- **All 38 routes registered** across 8 blueprints; route paths verified to match test_helpers/api_client.py expected paths exactly (e.g. /_clock/set_current_utc, /radon-tests/<id>/record-result, /mitigation-jobs/<id>/quote, /warranties/<id>/cancel).
- **Boot verified:** `PORT=8765 python3 app.py` serves on 0.0.0.0, foreground, reads $PORT (default 10000). start.sh: reads $PORT, binds 0.0.0.0, exec foreground, conditional pip install.
- **Storage in-memory only** (db.store recreated per process); NO entity seeding at startup (store begins empty except logical-clock default).
Implementation deemed complete and ready for Step 7. Any path/casing/behavioral gaps will be reconciled by the Step 7 diagnostic loop.

## Step 7: Run Tests and Iterate — 2026-06-26T15:54:00.000Z

**Iterations run:** 2 (initial diagnostic sweep → 1 batch of fixes → confirming green sweep).

**Root cause:** All 25 union-failing tests failed during *setup*, not assertion. Fixtures in `test_helpers/fixtures.py` were built on a single absolute clock anchor (`CLOCK_AFTER_48H = 2026-04-03`) internally inconsistent with the PRD's temporal gates:
- Default install window started at `2026-04-03T08:00:00Z` while clock at install time was `2026-04-03T00:00:00Z`, so `complete-install` correctly raised `ERR_INSTALL_NOT_DUE` (PRD §3.5: "the current instant at or after `install_start_utc`"). Implementation was correct.
- `setup_actionable_property` advanced the clock to a fixed absolute instant rather than relative to placement, so a second fixture call within one test placed a fresh test at the already-advanced clock and "advanced" by a no-op, making the 48h retrieval window unmet → silent retrieve failure → `ERR_INVALID_STATE` on the following `record-result`.

**Tests deleted:** None. Every failing test traced to a verbatim PRD sentence and was uniquely derivable; all were test-helper precondition bugs (STEP 2), not assertion or coverage problems.

**Fixes applied to `test_helpers/fixtures.py`** (re-anchored the lifecycle onto a self-consistent timeline landing warranty issuance at exactly `2026-04-03T00:00:00Z`, the instant multiple test_suite assertions pin):
- `setup_actionable_property`: place INITIAL test at `2026-03-30`, advance clock +48h to `2026-04-01` to retrieve; wrapped retrieve in `get_success_data` so a broken retrieve surfaces clearly.
- `setup_scheduled_job`: default install window → `[2026-04-01T00:00:00Z, 2026-04-01T04:00:00Z]` so `complete-install` at clock `2026-04-01` satisfies "at or after `install_start_utc`" (equality allowed per PRD).
- `place_post_mitigation_retest`: place POST_MITIGATION at `2026-04-01`, advance clock +48h to `2026-04-03` before retrieving; wrapped retrieve in `get_success_data`.

**Fix applied to `test_suite/test_04_job_lifecycle_cascades.py`:**
- `_arm_recurring_high_retest` helper: after firing the due retest at `2028-04-03` (places a fresh RECURRING test with a 48h window), advance the clock +48h to `2028-04-05` before retrieving it. Prior version retrieved with 0h-elapsed window — a latent bug masked because the install-window failure aborted the fixture upstream.

**Fixes applied to `implementation/`:** None. The `ERR_INSTALL_NOT_DUE` gate and 48h placement-window enforcement are both PRD-faithful; failures were entirely test-fixture preconditions.

**Final sweep result:** All 8 parallel rounds passed 65/65 (no flakiness). Orchestrator independently re-ran the full 8-round parallel sweep to confirm and persist durable evidence — all 8 `results.{1..8}.json` show passed=65/total=65/failed=0.

## Step 8: Finalize PRD — 2026-06-26T15:57:00.000Z

Step 7 made test_helpers/ + test_suite/ fixes (0 implementation fixes, 0 deletions), so the skip condition was NOT met — Step 8 ran.

**ZERO edits made.** `PRD_FINALIZED.md` is byte-identical to `PRD.md` (267 lines each, 0% delta; `diff -q` confirms IDENTICAL).

Both step_7_diff items are pure fixture/timeline-anchoring bugs (test_helpers/fixtures.py + one test_suite/ clock-advance helper); neither reveals a behavior the PRD left under-determined.
- **Item 1 — ERR_INSTALL_NOT_DUE gate:** PRD §3.5 states verbatim "the current instant at or after `install_start_utc`, else `ERR_INSTALL_NOT_DUE`"; impl `routes/mitigation_jobs.py:306` (`now < _install_start_dt` → raise; allows `>=`) is an exact inclusive match. No silence.
- **Item 2 — 48h placement/retrieval window:** PRD §3.2 states verbatim the elapsed difference "must be at least `placement_window_hours` hours"; impl `routes/radon_tests.py:169-171` (`elapsed < required` → raise; allows `>=`) is exact inclusive match. No silence.

Pre-edit enumeration confirmed all parallel temporal gates (retest fire-due `retest_schedules.py:62`, warranty refresh `warranties.py:75`, crew-window overlap, placement defaults) use the same inclusive convention the PRD already states verbatim. No implementation-pinned behavior left open by PRD → no patch warranted.

## Step 9: Complete PRD — 2026-06-26T16:04:00.000Z

Always runs. Source = PRD_FINALIZED.md (267 lines / 43,011 chars) → PRD_COMPLETED.md (267 lines / 46,928 chars, char delta +3,917; line count unchanged — all in-paragraph inserts/revisions, no new sections).

**13 changes — 6 mismatch-revisions, 7 ambiguity-pins:**
- §2.1 RBAC — revise/mismatch — `X-User-ID` recorded but never compared; any permitted-role caller may act on any resource (no ownership check) — middleware.py:23-46, all routes.
- §2.2 — insert/ambiguity — `api_request_timestamp` is real wall-clock, not the logical clock — response.py:29-31.
- §2.3 — insert/ambiguity — creation-order tie-break on `created_at` sort; exact per-endpoint filter query params (unknown ignored; properties takes none) — listing.py:11-16 + route filter dicts.
- §2.5 — revise/mismatch — creating/FK-bearing POSTs validate body fields up front (before FK-existence/state gates); pure path-addressed transitions defer body checks to last — radon_tests.py:43-64, mitigation_jobs.py:43-68/180-191.
- §2.6 — insert/ambiguity — later-creation-order tie-break for `latest_result_pci_l` when two RESULT_READY tests share created_at — domain.py:78-82.
- §3.2 retrieve — revise/mismatch — inspector-ACTIVE check targets test's assigned `inspector_id` (not caller), vacuous when null — radon_tests.py:181-184.
- §3.2 void — revise/mismatch — any Inspector or PlatformAdmin may void, no ownership — radon_tests.py:287-300.
- §3.5 balance gate — insert/ambiguity — `ERR_BALANCE_NOT_SATISFIED` atomic in record-result; on failure test stays RETRIEVED — radon_tests.py:255-272.
- §3.5 cascade — insert/ambiguity — warranty/schedule issuance only on first clear — jobs_cascade.py:104-110.
- §3.5 schedule — revise/mismatch — explicit gate order (deposit→crew→window→rush→crew-calendar); rush job w/o `closing_deadline_utc` fails ERR_RUSH_DEADLINE_MISSED — mitigation_jobs.py:206-233.
- §3.5 crew calendar — insert/ambiguity — "install day" = UTC date of `install_start_utc` — mitigation_jobs.py:250-284.
- §3.5 rework — insert/ambiguity — rework still checks `expected_property_version` but skips deposit + rush-deadline gates — mitigation_jobs.py:197/204-230.
- §3.6 refresh — insert/ambiguity — ERR_INVALID_STATE for non-ACTIVE; pre-term refresh is 200 OK no-op (no version bump) — warranties.py:67-80.
- §3.6 claim — insert/ambiguity — claim-driven rework clear reuses existing warranty, no 2nd warranty/schedule — jobs_cascade.py:104-110, warranties.py:130-169.
- §3.7 fire-due — insert/ambiguity — armed RECURRING test fields: SHORT_TERM_48HR, null inspector_id/mitigation_job_id, default 48h/4h warmup, logical-clock placement_start_utc — retest_schedules.py:71-92.

**PIPELINE COMPLETE.** `workspace/PRD_COMPLETED.md` exists on disk — termination signal satisfied. Final test state: all 8 parallel rounds 65/65 passing.
