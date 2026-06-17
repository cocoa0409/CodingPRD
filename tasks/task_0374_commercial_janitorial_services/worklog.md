# Worklog — task_0374_commercial_janitorial_services

## Step 1: Create Task Directory — 2026-06-15T17:02:52.000Z

Created `tasks/task_0374_commercial_janitorial_services/` with `workspace/` subdirectory. Output directory pre-assigned by orchestrator invocation (no index scan performed). Verified `./INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate Scaffold — 2026-06-15T17:31:47.000Z

Generated across three subagent passes (the first two subagents dropped on socket errors after writing their primary artifact; a fresh tightly-scoped agent completed each remaining file). All three files validated (PyYAML loads cleanly, correct single/multi top-level keys):

- SCAFFOLD.yaml (1381 lines) — §1.0–§1.7. Domain `commercial-janitorial-services`, api_prefix `/accounts`. Top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. Complexity profile: primary archetype temporal_windowing, secondary pricing_engine; layers = dual_variant_calculation (estimated labor vs clocked actual; provisional vs final invoice), cascading_side_effects (complaint→callback→credit→invoice recompute), optimistic_concurrency (OCC on Account.version + BillingPeriod.version), rate_threshold_triggers (quality-score gates billing holdback/callback escalation), derived_field_reconciliation. Entity topology flat; branching state machines. Roles include AccountManager, (crew/supervisor), ClientContact (X-User-ID == Site.contact_user_id), PlatformAdmin (test clock surface POST /_clock/set).
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (1171 lines) — §1.8, single top-level key scaffold_difficulty_design. Expert tier: 9 §0.5 rules × 2 instances each = 18 instances; all grounds[] refs resolve into SCAFFOLD §1.1–§1.7.
- SCAFFOLD_CORNER_DESIGN.yaml (2135 lines) — §1.9, single top-level key scaffold_corner_design. Expert-tier breadth: 63 total (50 non-stub + 13 `excluded_because:` stubs citing §1.8 by name). Per section: entities 13, state_machines 19, calculations 7, validations 8, endpoints 5, errors 2, rbac 4, cross_cutting_complexity_layers 4, consistency_model 1. All grounds[] refs resolve; every error_id in §1.6; every endpoint/role pairing matches §1.5/§1.7; numeric asserts computed against §1.3 formulas+constants (e.g. CALLBACK estimate 64 = ceil(ceil(8000/50)·0.40); MINOR credit 30000 = round(300000·0.10); periodic 12000; provisional total 312000). All 63 names unique and disjoint from the 18 §1.8 names. scaffold_lint.py: zero violations against either design file (21 remaining VERDICTs are pre-existing SCAFFOLD §1.1↔§1.5 FK_REVERSE_UNREACHABLE heuristic flags on filtered-list GETs, scaffold-level and out of scope).

## Step 3: Copy Shared Files — 2026-06-15T17:31:47.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0374_commercial_janitorial_services/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-15T17:36:32.000Z

Generated `workspace/PRD.md` (283 lines) from SCAFFOLD.yaml only. Sections: 1. Introduction; 2. Global Specs (2.1 RBAC — 4 opaque-identity roles, ClientContact site-ownership; 2.2 response envelope; 2.3 pagination; 2.4 identity/timestamps/versioning incl. InvoiceLine common_fields:false carve-out; 2.5 nested FK resolution; 2.6 validation ordering priority 1–8; 2.7 monetary precision half-up/per-component/ceil; 2.8 OCC on billing-period transitions — expected_account_version, ERR_STALE_VERSION 412; 2.9 cascade/reconciliation discipline); 3. Business Logic (11 subsections: accounts/sites, crews/routes/schedule, visits, time clock, completion+billing settlement, periodic add-ons, complaints/callbacks/credits, inspections/quality, contracts/billing-period lifecycle, supplies, test clock); 4. Endpoint Definitions (64 endpoints, 4-col table); 5. Error Code Catalogue (24 IDs, 2-col table).

Hard-contract self-check passed: every error ID appears ≥twice (prose + §5 table); §3 contains no path/HTTP-method backtick tokens; all 60 scaffold field/param names covered. Confirmed: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read/grepped/referenced; no sibling task_*/ accessed.

## Step 5: Generate Unit Tests — 2026-06-15T17:43:00.000Z

Test files: 9 (8 test_*.py + conftest.py) in test_suite/. Total tests: 86, every one carrying exactly one `Design:` tag.

Queue A — Difficulty (depth): 36 tests / 18 instances (all 9 rules × 2 instances × 2 tests each):
- test_06_labor_and_billing_calc.py — dual_variant_calc, combinatorial_formula (8 tests)
- test_07_workflows_cascades.py — non_linear_state_machine, transitive_cascade (8 tests)
- test_08_constraints_concurrency.py — priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant (20 tests)

Queue B — Corner (breadth): 50 tests / 50 non-stub instances (≥1 each), across test_01–test_05: entities (13), state_machines (15), calculations (5), validations (5), endpoints (5), errors (1), rbac (4), consistency_model (1); the cross_cutting_complexity_layers section is entirely excluded stubs.

Instances SKIPPED: none on PRD-coverage grounds — every difficulty instance and every non-stub corner instance passed the PRD-first two-condition filter. The 13 `excluded_because:` corner stubs were correctly not translated (no test_recipe; cited difficulty instance owns the assertion); all 13 stub difficulty_instance cross-refs verified to resolve to real instances.

test_helpers/ files (9): __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py.

Key notes: all four roles identity:opaque (test_users.py uses shared constants); ClientContact ownership threaded via Site.contact_user_id="cc-1" matching canonical X-User-ID, with make_client_contact_headers() handling wrong-site (cc-999) negatives. InvoiceLine (common_fields:false) typed/asserted with id+created_at only. All 86 PRD citations grep-verified verbatim against PRD.md. The two priority-precedence difficulty instances grounded in PRD §2.6 fixed-priority ordering (pass unique-derivability). All files py_compile clean.

## Step 6: Generate Implementation — 2026-06-15T17:43:00.000Z

Built Python + Flask REST API in workspace/implementation/. Files: start.sh (exec), requirements.txt (flask==3.0.3), app.py (entry + all 60 routes, error handlers, validation ordering, state machines), db.py (in-memory Store dicts + common-field/timestamp helpers), errors.py (ApiError + error-ID→HTTP-status catalog), response.py (envelope helpers), middleware.py (auth extraction + RBAC), helpers.py (body parse/validate, pagination, half-up rounding), services.py (serialization, all 5 calculations, billing recompute, cascades).

Stack/storage: Python 3 + Flask, in-memory only (module-level db Store dicts). No SQLite/disk/seeding — every boot empty; tests build state via API. Money uses decimal.Decimal ROUND_HALF_UP; minute estimates math.ceil. start.sh reads $PORT (default 10000), guards pip install on cheap `import flask` check, then exec python3 app.py binding 0.0.0.0:$PORT foreground (threaded=True).

Self-smoke-tested: envelope, auth/RBAC ordering (401→403→ERR_NOT_SITE_CONTACT→404→404 FK→422→409 state→business), estimate vs actual labor, periodic charge (per-component rounding + 1.5× overage = 16500), callback credit (MAJOR +5pts = 15000), provisional vs final holdback (5000), OCC on account.version (412 stale, increments on close/reopen), invoice-line emit/delete on close/reopen, crew double-booking (half-open, adjacency allowed), schedule window (closed-interval conflict), shift capacity, duplicate period, pagination bounds, no-auth /_clock/set. InvoiceLine carries only id/created_at.

Judgment calls (PRD ambiguities): (1) Account-ACTIVE gate enforced on site creation (ERR_ACCOUNT_NOT_ACTIVE) and schedule creation (ERR_SITE_ARCHIVED when site archived); contract creation DRAFT-only so account/site gate enforced at activation per state machine, not at contract creation. (2) /_clock/set exempt from auth headers but rejects present-but-wrong role (non-PlatformAdmin) 403; clock value stored but no workflow consumes it (month derived from each service_date string). (3) Billing-period auto-open on completion/credit only if contract ACTIVE and no period exists for contract+month, else visit/credit not captured. (4) close accepts OPEN and REOPENED; reopen accepts only CLOSED. All impl + tests py_compile clean.

## Step 7: Run Tests and Iterate — 2026-06-15T18:03:00.000Z

### Fix subagent (long-lived loop) report — verbatim

Iterations run: 2 (1 baseline sweep to surface failures, 1 verification sweep after fixes). Final state reported: 8/8 rounds at 85/85.

The baseline 8-round sweep produced a stable union of 4 failing tests (all failing 8/8 rounds — deterministic).

Tests deleted (1):
- `test_close_billing_period_with_in_progress_visit_returns_visit_in_progress` (test_suite/test_02_state_machines.py) — BRANCH-ASYMMETRIC / unreachable-branch collapse (STEP 1b). PRD §3.9 defines the close gate as "no visit captured into this period (any visit whose billing_period_id equals the period's id) is currently IN_PROGRESS." Per the visit state machine, billing_period_id is set ONLY at completion (§3.5), which simultaneously makes the visit COMPLETED — so a visit can never be both captured and IN_PROGRESS; the gate is unreachable through any PRD operation sequence. The test created an uncaptured IN_PROGRESS visit (null billing_period_id) and asserted it blocks close, contradicting the PRD parenthetical. SCAFFOLD_CORNER_DESIGN.yaml line 739 acknowledged the contradiction and substituted a "same month/contract IN_PROGRESS" reading the PRD prose does not support — a scaffold-only rule. The implementation's check (app.py:1214) is the unique PRD-faithful reading and was not weakened.

Fixes applied to test_suite/ (2):
- test_08_constraints_concurrency.py, helper _setup_crew_near_capacity — replaced bare undefined `api.create_time_entry(...)` with module-level `api_client.create_time_entry(...)` (already imported). Fixed NameError for test_shift_capacity_exactly_at_cap_allowed and test_shift_capacity_one_over_cap_rejected.
- test_02_state_machines.py, test_complete_visit_with_open_time_entry_returns_open_time_entry — ERROR PRECEDENCE SILENCE (STEP 1b). Setup trips BOTH completion gates (one OPEN entry, zero COMPLETED). PRD §3.5 lists both (ERR_NO_TIME_ENTRY, ERR_OPEN_TIME_ENTRY) without pinning precedence; relaxed to validate_error_is_one_of([ERR_OPEN_TIME_ENTRY, ERR_NO_TIME_ENTRY]) (explicitly-permitted relaxation), keeping the faithful IN_PROGRESS post-state assertion.

Fixes applied to test_helpers/: none. Fixes applied to implementation/: none (subagent's verification sweep).

### Orchestrator independent re-verification + flakiness fix (not part of subagent run)

The subagent's per-sweep `rm -f` removed its results files on exit, so the orchestrator re-ran the documented 8-round parallel sweep to persist results.{1..8}.json AND independently confirm. The first orchestrator sweep revealed FLAKINESS the subagent's single verification sweep had missed: rounds 2 and 6 each failed `test_shift_capacity_exactly_at_cap_allowed` with `requests.exceptions.ConnectionError: BadStatusLine('GET /time-entries/<id> HTTP/1.1')` — Werkzeug dev server (app.run, threaded=True) corrupting reused keep-alive connections under the ~8× concurrent host load. This is a server-robustness bug, not a PRD-semantic one (the test passed 6/8 rounds; logic is faithful).

Orchestrator implementation fix (pure server infrastructure, no PRD-semantic change, no new endpoint/field/side-effect): switched the `__main__` block in app.py to serve via waitress (robust pure-Python WSGI server) when importable, falling back to app.run otherwise; added waitress==3.0.0 to requirements.txt; broadened start.sh install guard to `import flask, waitress`.

Post-fix verification: TWO consecutive full 8-round parallel sweeps (16 rounds total) all passed 85/85 with zero failures/errors. results.{1..8}.json persisted in workspace/implementation/ from a clean 8-round sweep.

Net Step 7 delta vs baseline: 1 test deleted, 2 test_suite/ fixes, 0 test_helpers/ fixes, 1 implementation/ fix (waitress WSGI server swap). Step 8 is NOT skipped (deletions + test_suite fixes + 1 impl fix occurred).

## Step 8: Finalize PRD — 2026-06-15T18:06:00.000Z

Produced workspace/PRD_FINALIZED.md as a minimal patch of PRD.md. Line counts: 283 → 283 (one line revised in place; ~0.35% changed).

Single change:
- §3.5 — revise — Pinned visit-completion gate error precedence: the completed-count gate (ERR_NO_TIME_ENTRY) is evaluated before the open-entry gate (ERR_OPEN_TIME_ENTRY); when both are tripped the request returns ERR_NO_TIME_ENTRY — implementation/app.py:638-641.

No edit for: waitress server swap (infrastructure-only, no PRD-observable behavior); crew-near-capacity NameError (pure test-fixture bug); deleted close-gate test (PRD §3.9 already uniquely pins the close gate — billing_period_id assigned only at completion (app.py:650) right after COMPLETED (line 644), so a captured visit can never be IN_PROGRESS; impl check at app.py:1214 matches the PRD definition exactly).

Pre-edit NO-NEW-MISMATCH search (edit 1): grepped ERR_NO_TIME_ENTRY|ERR_OPEN_TIME_ENTRY|has_completed|has_open across implementation/*.py; both errors raised at exactly one site each (app.py:638 `if not has_completed`, app.py:641 `if has_open`), both inside the single complete_visit handler (lines 628-657); errors.py:26-27 only registers HTTP status. Unique site → precedence statement contradicts no other path. Wording kept the original two-condition sentence and appended the fixed-order/tie-break clause to avoid narrowing other behavior.

## Step 9: Complete PRD — 2026-06-15T18:09:00.000Z

Produced workspace/PRD_COMPLETED.md from PRD_FINALIZED.md via a full PRD-vs-implementation/ completeness scan. Line counts: 283 → 283 (all in-paragraph; no new sections). Char delta: 42,733 → 45,970 (+3,237). 9 changes total: 8 ambiguity-pins, 1 mismatch-revision.

Per-change list:
- §3.1 — revise — mismatch — corrected "blocks creation of new sites, visits, and contracts" to: impl gates only site creation with ERR_ACCOUNT_NOT_ACTIVE and gates the account at contract activation; contract/visit creation under a suspended account is not blocked; suspend has no state precondition — app.py:230,244 / 296-331 / 552-580 / 211-218.
- §3.1 — insert — ambiguity — site archive has no state precondition; sets ARCHIVED from any status — app.py:283-290.
- §3.2 — insert — ambiguity — crew deactivate has no state precondition; sets INACTIVE from any status — app.py:422-429.
- §3.2 — insert — ambiguity — schedule creation requires site ACTIVE (ERR_SITE_ARCHIVED) and crew AVAILABLE (ERR_CREW_INACTIVE), checked before window-conflict — app.py:453-459.
- §3.4 — insert — ambiguity — clock_out_min body range 1..1440 (ERR_INVALID_REQUEST) validated before OPEN-state and clock-range checks; OPEN-state failure is ERR_INVALID_STATE — app.py:744-749.
- §3.5 — insert — ambiguity — completion settles only into an OPEN period of the site's currently ACTIVE contract; if a period for that contract/month exists in any non-OPEN state no new period opens and the visit is not captured; no active contract → no settlement — app.py:126-153,646-650.
- §3.7 — insert — ambiguity — credit uses the site's currently ACTIVE contract (none → credit 0); when no OPEN period exists for the callback month, credit_applied_cents is still set on the complaint but attached to no period — app.py:1067-1076.
- §3.9 — insert — ambiguity — periodic_cents sums only COMPLETED PERIODIC captured visits with resolvable job+contract — services.py:164-171.
- §3.9 — revise — mismatch — callback_credit_cents summed by the complaint's posted-period reference, not current RESOLVED status, so a reopened complaint's posted credit stays counted (consistent with §3.7 "not clawed back") — services.py:173-179, app.py:1097-1099.
- §3.11 — insert — ambiguity — /_clock/set requires to_iso8601 (else ERR_INVALID_REQUEST; format otherwise unvalidated); accepted with no auth headers but a present X-User-Role must be PlatformAdmin (else ERR_FORBIDDEN); returns 200 empty data — app.py:1344-1355.

Deliberately not changed: PRD §3.5's internal cross-ref to "the provisional total formula of §3.8" actually points at Inspections (formula is in §3.9) — a PRD cross-ref slip, not an impl-behavior ambiguity, left untouched per minimal-edit rule. Additive list-filter query params (status filters on accounts/complaints/billing-periods) non-contradictory, no pin needed.

## Pipeline Complete — 2026-06-15T18:09:00.000Z

All 9 steps done. Final state: 85 tests, 16/16 parallel rounds green (two consecutive 8-round sweeps) under prd-bench-local-run --isolation per-test-server. Artifacts present: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9) + test_suite/ (9), workspace/implementation/ (Python+Flask, waitress WSGI) with results.{1..8}.json all passing.
