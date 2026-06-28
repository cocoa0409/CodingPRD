# Worklog — task_0655_air_duct_dryer_vent_cleaning

## Step 1: Create Task Directory — 2026-06-26 (pre-assigned)

Task directory `tasks/task_0655_air_duct_dryer_vent_cleaning/` and its `workspace/` subdir pre-created. Index/folder name used verbatim as assigned (no auto-index scan). Scenario: Air-Duct & Dryer-Vent Cleaning (home profile & system count, inspection & before/after camera, service & pricing, add-ons, recurring plan & reminder, route/crew, HVAC-repair upsell referral, callback). Difficulty: Expert.

## Step 2: Generate Scaffold — 2026-06-26T15:11:00.000Z

All three scaffold artifacts written and lint-clean (`VERDICT: clean lint`).
- `SCAFFOLD.yaml` (§1.0–§1.7, 1363 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 1204 lines), `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 1495 lines).
- Entities: 11 (PricingConfig, Homeowner, Home, HvacSystem, CrewMember, RoutePlan, WorkOrder, Inspection, RecurringPlan, UpsellReferral, CallbackTicket).
- Endpoints: 43 (incl. `/_clock/set_current_utc` default 2026-04-01). Error codes: 38.
- State machines: 6 (WorkOrder cyclic re-inspect loop; RoutePlan compound; RecurringPlan parallel dims reminder_status × lifecycle_status; UpsellReferral branching fork; CallbackTicket self-referential reopen cycle).
- Calculation variants: 4 variant blocks across 7 calculations (estimate vs invoice dual-variant; contamination_risk_score; tiered pricing pinned eval order + nested rounding; non-linear duration; reminder projection; route-minutes reconciliation; slot-overlap geometry). Concurrency: 2 OCC rules (RoutePlan.version, Home.version).
- §1.8: 18 instances (9 rules × 2). §1.9: 36 instances (35 active + 1 stub) across all 9 claim-extraction sections.
- Note: endpoint (43) and error (38) counts modestly above Expert ceilings (32/30) — every endpoint load-bearing (FK reverse-reachability / distinct tested transition), every error triggerable (≥2× referenced). `api_prefix: ""` (flat peer entities). All formula asserts pinned as literals (estimate 36720 vs invoice 32832; pinned-order total 50949; multi-system boundary 12960@n=1 vs 15552@n=2; duration 105 w/ big-home factor; risk score 48 ≥ threshold 40).

## Step 3: Copy Shared Files — 2026-06-26T15:13:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0655_air_duct_dryer_vent_cleaning/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T15:17:00.000Z

PRD written to `workspace/PRD.md` (303 lines). Did NOT open either withheld design file.
- §1 Introduction; §2 Global Specs (2.1 RBAC 4 roles + identity translations, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Common Props, 2.5 Cascades, 2.6 Nested Retrieval/left-to-right path validation, 2.7 Money/Minutes/Rounding, 2.8 OCC, 2.9 Logical Clock & Scheduled Actions, 2.10 Order of Validation); §3 Business Logic (11 lifecycle subsections — all state machines, dual-variant estimate/invoice engine, duration formula, committed-minutes ledger, slot-overlap geometry, contamination risk score, reminder cadence, referral TTL); §4 Endpoint table (43); §5 Error catalogue (38).
- Hard Contracts: Contract 1 Field coverage PASS (58/58 entity fields, 51/51 params); Contract 2 Rule coverage PASS (all transitions/7 calcs/2 OCC/validations); Contract 3 Path purity PASS (0 path-like tokens in §3, 374 scanned).
- Constants embedded in prose: clock default 2026-04-01T00:00:00Z, 2-system threshold, 15-min buffer, durations 20/35/15/25/10, 1.25 big-home factor @3000 sqft, weights 8/2, ceiling 100, threshold 40, 30-day referral TTL, cadences 6/12/24.

## Step 5: Generate Unit Tests — 2026-06-26T15:30:00.000Z

(launched concurrently with Step 6)
test_helpers/ (9 files): `__init__.py`, `types.py` (11 entity TypedDicts + 10 status enums + role enum), `api_client.py` (~40 methods), `api_errors.py` (37 errors + HTTP map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque PlanAdmin/Dispatcher headers + `make_technician_headers(crew_id)`/`make_homeowner_headers`), `fixtures.py`.
test_suite/ (conftest.py + 5 files, **72 tests**): test_01_pricing_and_duration, test_02_workflows_and_cascades, test_03_routes_and_commits, test_04_plans_referrals_config, test_05_difficulty_second_pass.
- Coverage (design-index-only): Queue A (Difficulty) **18/18** translated, ≥2 tests each (37 difficulty-tagged). Queue B (Corner) **35/35** non-stub translated (≥1 each, 35 corner-tagged). 1 stub correctly not translated. 0 skips overall (PRD verbatim-covers all 53 rules).
- All numeric literals independently recomputed with round-half-up (estimate 36720 / invoice 32832 / 19440 / 50949 / 12960 / 15552 / duration 105/80/90 / risk 48/24 / second-pass 11016/19440). All 72 collect cleanly. Every difficulty instance ≥2 tags, every corner non-stub ≥1, no orphan/dual tags. 81 citation spans (≥8 words) verified verbatim in PRD.md. No scaffold/§1./Table refs, no skip/xfail.

## Step 6: Generate Implementation — 2026-06-26T15:41:00.000Z

(launched concurrently with Step 5; first attempt died on a transient API error after writing only empty scaffolding — partial dir removed and Step 6 re-run fresh with an added hard-isolation constraint forbidding reads of the now-existing test_suite/test_helpers.)
13 files in `workspace/implementation/`: `start.sh` (foreground, reads $PORT default 10000, binds 0.0.0.0, `exec python3 app.py`, guarded pip install), `requirements.txt` (Flask 3.0.3), `app.py` (43 routes + error handlers + validation ordering), `clock.py` (default 2026-04-01T00:00:00Z), `db.py` (in-memory dicts, no seeding), `errors.py`, `response.py`, `middleware.py` (auth + RBAC), `common.py` (round_half_up via Decimal, add_months, pagination), `constants.py`, `lookups.py`, `serializers.py`, `services.py`.
- **43 endpoints** (matches PRD §4 exactly incl. `/_clock/set_current_utc`). Validation precedence per PRD §2.10. All 11/13 modules compile cleanly (verified `py_compile`).
- Subagent live smoke tests confirmed: envelope, auth 401/RBAC 403/404/400, pricing engine round-per-step, duration big-home surcharge, WorkOrder re-inspect loop, route commit buffered half-open overlap + ERR_OUTSIDE_SHIFT + zone/UV-cert + OCC 412, crew double-booking, committed-minutes ledger reversal on cancel, completion cascades (UpsellReferral + DUE-plan acknowledge), reminder cycle w/ drift-free add_months, clock-driven referral TTL expiry, fresh-boot isolation (0 entities + default clock after restart).

## Step 7: Run Tests and Iterate — 2026-06-26T16:42:00.000Z

One long-lived fix subagent owned the run-diagnose-fix-rerun loop. The 8-round parallel stability sweep ran in the foreground (all 8 rounds launched in one bash invocation, joined with `wait`), `--isolation per-test-server --timeout 120 --test-timeout 30`, results written to `results.{1..8}.json`.

- **Iterations run: 1.** The very first 8-round sweep was clean — all 8 rounds `passed == total == 72`, `failed=0, errors=0, skipped=0`. No flakiness surfaced across the parallel sweep. (Independently re-verified on disk by the orchestrator: all 8 `results.{1..8}.json` show 72/72.)
- **Tests deleted: 0** — no test failed in any round, so no PRD-coverage / unique-derivability deletions were triggered.
- **Fixes applied to `test_helpers/`: 0** (none required).
- **Fixes applied to `implementation/`: 0** (none required).
- Subagent note: an initial parse pass mis-keyed on a nonexistent `outcome` field before correcting to the schema's `status` field; the raw JSON confirms all 72 tests pass in all 8 rounds. PRD.md already determined every behavior the implementation exhibits.

## Step 8: Finalize PRD — SKIPPED — 2026-06-26T16:43:00.000Z

Skipped per the skill's skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). No `PRD_FINALIZED.md` produced. Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-26T16:48:00.000Z

Full PRD-vs-`implementation/` scan. Source `PRD.md` (PRD_FINALIZED.md absent) → `workspace/PRD_COMPLETED.md`. Lines 303 → 303 (all edits in-paragraph / in-table-cell; no new sections). Char delta **+2166**.

- **11 changes — 8 ambiguity-pins, 3 mismatch-revisions.**
- Mismatch-revisions (the material ones): (1) §2.1 RBAC — impl authorizes by role membership only; `X-User-ID` is never compared to any entity FK, so the per-instance ownership scoping for Technician/Homeowner is not enforced (`middleware.py:14-32`, `app.py:68-72`). (2) §2.8 OCC — stale-route-version check is the **last** commit guard (after the read-only slot-overlap test, before any mutation), per §2.10's "finally the version checks" (`app.py:579-585`). (3) §3.8 contamination risk score — dead code: never computed/stored/returned; referral creation gated **solely** by the AFTER inspection's `recommend_hvac_repair` flag, not by "score ≥ 40" (`app.py:868-876`, `services.py:192-206` uncalled).
- Ambiguity-pins: §2.3 pagination clamping (limit→[1,100], offset→≥0; non-int → ERR_INVALID_REQUEST); §2.9 all server instants from logical clock; §3.1 homeowner email-collision → ERR_INVALID_REQUEST; §3.1 HvacSystem decommission idempotent (no state guard); §3.8 complete-request body shape pinned; §3.8 invoice reads `active_system_count` + `has_active_plan` live at completion; §3.9 forced re-eval of already-DUE reminder is no-op success + plan-not-ACTIVE check precedes due check; §4 undocumented list filters (`GET /homes/{id}/systems` by `status`, `/recurring-plans` by `lifecycle_status`).

**Pipeline complete.** `workspace/PRD_COMPLETED.md` exists on disk (47388 bytes). All 72 tests pass across all 8 stability-sweep rounds.
