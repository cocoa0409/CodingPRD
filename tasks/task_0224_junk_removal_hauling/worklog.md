# Worklog — task_0224_junk_removal_hauling

## Step 1: Create task directory — 2026-06-07T11:37:50.000Z

Created `tasks/task_0224_junk_removal_hauling/` and `tasks/task_0224_junk_removal_hauling/workspace/` (index assigned by caller, Step 1 scan skipped per instructions).

## Step 2: Generate scaffold (Expert) — 2026-06-07T12:01:26.000Z

All three scaffold artifacts are complete and validated. Here is the summary for the orchestrator's worklog.

## Task 0224 — Junk Removal & Hauling (Expert) — scaffold generated

All three files written to `tasks/task_0224_junk_removal_hauling/` and pass `scaffold_lint.py` with **VERDICT: clean lint** (41 endpoints, 11 entities, 463 setup/trigger calls scanned across §1.8+§1.9).

**Archetype:** pricing_engine + temporal_windowing; cyclic state-machine shape; peer_roles; immediate consistency. Layers: dual-variant calculation, cascading side effects, derived-field reconciliation, optimistic concurrency.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **Entities (11):** PricingPolicy, Customer, Crew, Truck, HaulJob, JobItem, PhotoEstimate, Dispatch, DiversionRecord, DumpTicket, Invoice. Money in integer cents; truck fractions billed in eighths.
- **State machines (4):** HaulJob (8 states, DRAFT→…→COMPLETED/CANCELLED with a SCHEDULED↔ESTIMATED revision **cycle**); Dispatch (RESERVED→ACTIVE→RELEASED/VOIDED); Invoice (**parallel dimensions** billing_status × dispute_status); PhotoEstimate (SUBMITTED→ACCEPTED/SUPERSEDED).
- **Concurrency (2 OCC rules):** dispatch-create-stale-crew (parent Crew, 412), revise-stale-job (parent HaulJob, 412) — both with required `expected_*_version` input and version bump.
- **Calculations (7):** estimated_truck_fraction, estimated_total_cents (estimate variant), final_total_cents (final variant — Rule 2 mode-a nonlinear; per-item-then-sum rounding = mode-b), dump_fee_passthrough (WEIGHT_BASED vs VOLUME_BASED variants), cancellation_fee, crew_reserved_minutes, customer_outstanding_balance.
- **Validations (11):** auth→authz→existence→request→state→referential→safety(freon/hazmat)→temporal(crew-buffer / truck half-open)→fiscal(credit limit)→OCC.
- **Endpoints (41):** higher than the 20–32 guideline because FK reverse-reachability (lint check f) is a hard requirement across 11 entities; `api_prefix` set to `""` and parent path params normalized to `{id}` so segment derivation resolves. Includes one `/_clock/set_current_utc` test-driving endpoint.
- **Errors (36):** all triggerable/referenced. **Roles (5):** PlatformAdmin (opaque), Customer (entity_backed:Customer), Dispatcher (opaque), CrewLead (entity_backed:Crew), Billing (opaque).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rules × 2 = **18 instances**, all grounded in §1.1–§1.7, all formula-derived asserts pre-computed as literals (e.g. final_total 54486, estimate 27750, dump weight 7200 vs volume 6000, same-day 19440, cancel fees 1875/3750).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **31 instances** (27 active + 4 `excluded_because` stubs) across all 9 claim-extraction sections — creation/required-field/not-found/computed, invalid-transition/terminal-lockdown/idempotency, calc correctness (same-day uplift, donation credit 6480), validation violations, endpoint reads, error triggers, RBAC denials, OCC stale-version, consistency.

49 instance names unique across both design files; all stub references resolve. No forbidden concurrency vocabulary; design keys correctly isolated to their own files.

## Step 3: Copy INSTRUCTION.md — 2026-06-07T12:01:26.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0224_junk_removal_hauling/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T12:07:16.000Z

Generated `workspace/PRD.md` (306 lines, ~42 KB) from the Junk Removal & Hauling scaffold. Withheld design files were not opened.

**Document metrics:** 5 top-level sections; 11 §2 subsections, 10 §3 subsections; §4 endpoint table 41 rows; §5 error table 36 rows.

**Hard contracts:** Field coverage 68/68 PASS; Rule coverage PASS (10 validations w/ full 1→10 ordering in §2.7; 2 OCC rejections; all state-machine edges; 7 calculations; sibling-branch symmetry for dump variants / diversion / parallel invoice dimensions); Path purity (§3) PASS (0 path-like tokens).

**Notable coverage decisions:** dual-variant calcs scattered (estimate §3.3 vs final §3.7; weight vs volume dump fee in §2.8/§3.3/§3.7); validation priority 1–10 as explicit ordered sentence in §2.7; constants embedded with unit/default context (buffer 30min, fraction step 0.125 eighths, same-day 0.20, tax 0.08, cancel 0.25/0.50, credit_limit 50000); dispatch input params split §3.4 core + §2.10 OCC; DiversionRecord/DumpTicket noted as common_fields:false (id+created_at only).

## Step 5: Generate unit tests — 2026-06-07T12:22:38.000Z

Generated complete test infrastructure for **task_0224_junk_removal_hauling** under a strict design-index-only contract.

**Stage 1 — `test_helpers/`** (9 files): `types.py` (status/role enums + entity TypedDicts, with `DiversionRecord`/`DumpTicket` correctly modeled as append-only id+created_at only), `api_errors.py` (all 38 error IDs + HTTP status map registered with the framework), `api_client.py` (one method per PRD endpoint), `constants.py` (canonical std_policy rate set + defaults), `factories.py` (input-only payload factories), `assertions.py` (per-entity + append-only checkers), `test_users.py` (5 roles; per-instance builders for the two `entity_backed` roles Customer/CrewLead), `fixtures.py` (5-tier composite helpers driving DRAFT→ESTIMATED→SCHEDULED→DISPATCHED→ON_SITE→LOADED→COMPLETED plus cancellation-invoice path, with correct identity threading), and `__init__.py` barrel export.

**Stage 2 — `test_suite/`** (conftest + 4 test files):
- `test_01_pricing_calculations.py` (14 tests)
- `test_02_lifecycle_and_cascades.py` (19 tests)
- `test_03_scheduling_guards.py` (17 tests)
- `test_04_intake_rbac_and_reads.py` (13 tests)

**Counts:** 63 tests total, 63 `Design:` tags (1:1, none untagged/dual-tagged/skipped).
- **Queue A (Difficulty):** all 18 instances covered, each by exactly 2 tests (36 tests).
- **Queue B (Corner):** all 27 non-stub instances covered by ≥1 test (27 tests).

**Skipped:** none of the translatable instances. The 4 corner `excluded_because` stubs (`revision_cycle_back_to_estimated_covered_by_difficulty`, `estimate_vs_final_divergence_covered_by_difficulty`, `crew_reserved_minutes_reconciliation_on_release_covered`, `complete_atomic_invoice_and_balance_visible_same_response_covered`) were not translated per spec — all four `difficulty_instance` cross-references verified to resolve to real §1.8 instances.

**Verification performed:** every PRD citation (all 48 distinct quoted sentences) confirmed to survive a literal `grep` of `workspace/PRD.md`; all priority-precedence tests (state>fiscal, safety>temporal) grounded in PRD §2.7's explicit fixed ordering; all pinned cents values copied verbatim from the design YAML (the one self-derived value, SCHEDULED cancellation fee 5438 = round(21750×0.25), follows PRD round-half-up); all files compile; all fixture/factory references resolve; no skip/skipif/xfail.

## Step 6: Generate implementation — 2026-06-07T12:22:38.000Z

Built a complete Python + Flask in-memory REST API for the Junk Removal & Hauling benchmark task. All smoke tests pass (full lifecycle, tiered/same-day pricing, OCC, parallel invoice dimensions, ledger reconciliation, hazmat/window/credit guards, cancellation, revision loop). Boots cleanly from a fresh process with an empty store (no seeding).

### Files (`workspace/implementation/`)
- `start.sh` — foreground launcher; reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on `import flask`, `exec python3 app.py`
- `requirements.txt` — `flask==3.0.3`
- `app.py` — entry point, blueprint registration, error handlers (ApiError + fallbacks all return standard envelope)
- `db.py` — in-memory store (dicts keyed by id, monotonic `_seq` for creation ordering)
- `errors.py` — full error catalog as `(error_id, http_status)` tuples + `ApiError`
- `response.py` — success/list/error envelope helpers (`meta`/`response_type`/`data`, `req_` request ids, 3-fractional-digit ISO timestamps)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, five roles, role gate
- `models.py` — entity constructors, common-field stamping (`created_at`/`updated_at`/`version`), `touch()` mutation bump, lean DiversionRecord/DumpTicket, serializers
- `helpers.py` — JSON body parsing, field/type/enum validation, pagination (limit 10/1-100, offset 0+), creation-order sort
- `clock.py`, `util.py` — test clock, uuid/timestamp/`round_half_up` (Decimal) utilities
- `routes/config.py`, `routes/haul_jobs.py`, `routes/dispatches.py`, `routes/invoices.py`
- `services/calc.py` (pricing engine), `services/recompute.py` (crew reserved_minutes + customer outstanding recomputed from source sets), `services/lookups.py`

### Endpoint count: 41 routes — matches PRD §4 exactly.

### Notable design choices
- All structural names read from PRD/scaffold (envelope, error, pagination, OCC, headers).
- Decimal + round-half-up at every named rounding point; never float for money.
- Validation priority order per PRD §2.7 (auth → forbidden → existence L-to-R → well-formedness/no-active-policy → state → cross-entity → hazmat 422 → temporal → credit 402 → OCC 412). Missing OCC field = ERR_INVALID_REQUEST (p4); mismatched = ERR_STALE_* (p10).
- Window semantics: crew buffer requires ≥ buffer_minutes gap (overlap fails); truck half-open [start,end) intersection (boundary-adjacent allowed).
- Ownership: Customer matches customer_id; CrewLead matches crew_id reached through the job's RESERVED/ACTIVE dispatch.
- Cascades atomic + derived fields reconciled by recomputation with per-owner version/updated_at bumps; DiversionRecord/DumpTicket kept lean.
- Default credit_limit_cents 50000 blocks completion/dispatch when exposure exceeds it — tests must set higher limit for large-total jobs (per PRD §2.9).

## Step 7: Run tests and iterate — 2026-06-07T12:36:42.000Z

All tests pass. Exiting with the summary.

**Iterations run:** 2 fix iterations, then 2 consecutive confirmation sweeps. Final state: two back-to-back clean 8-round parallel sweeps (16 rounds, 63/63 every round).

**Initial state:** 57/63 deterministic across all 8 rounds (6 hard failures); a flaky 7th surfaced only after the first fix.

**Tests deleted:** None. Every failure traced to either a test bug (STEP 2) or an implementation/server robustness issue (STEP 3) — all assertions are PRD-covered and uniquely derivable.

**Fixes applied to `test_suite/`:**
- `test_03_scheduling_guards.py` — the 8 `validate_success(api.create_dispatch(...))` calls that wrap a *successful* first/second dispatch creation were missing `expected_status=201`, so they defaulted to asserting HTTP 200. PRD §4 states "Operations that create a new, stand-alone resource or append a new resource to a collection return a `201 Created` status code," and §4's endpoint table lists `POST /dispatches` as a create. The implementation correctly returns 201; the test assertion was wrong. Added `expected_status=201` to all 8 (fixes `test_dispatch_freon_with_window_conflict_nonhazmat_returns_crew_not_hazmat`, `test_crew_buffer_gap_violation_rejected`, `test_crew_buffer_gap_exactly_met_is_allowed`, `test_truck_halfopen_overlap_rejected`, `test_truck_halfopen_adjacent_window_allowed`, `test_dispatch_with_stale_crew_version_rejected`). The fix makes the tests *more* faithful to PRD §4, not less.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**
- `app.py` (`__main__`) — switched the WSGI server from the Werkzeug dev server (`app.run(threaded=True)`) to `waitress` (`serve(app, ..., threads=8)`), with an `ImportError` fallback to the dev server. Root cause of the 1-in-8 flaky `requests.exceptions.ConnectionError: BadStatusLine('POST /haul-jobs ...')`: the test client uses a pooled `requests.Session` (HTTP keep-alive), and the Werkzeug dev server's keep-alive handling races with the client under the 8× concurrent per-test-server load, intermittently resetting reused connections. Waitress handles concurrent keep-alive connections reliably.
- `requirements.txt` — added `waitress==3.0.0`.
- `start.sh` — broadened the dependency short-circuit check from `import flask` to `import flask, waitress` so the install step runs when waitress is missing even if flask is already present.

No implementation business-logic checks were weakened, and no entity data is seeded at startup (storage remains in-memory dicts in `db.py`).

**Orchestrator confirmation sweep (2026-06-07T12:38Z):** Step 7 subagent's final results files had been cleaned up, so the orchestrator re-ran the full 8-round parallel sweep to regenerate the required artifacts. Result: all 8 rounds 63/63 passed=63 failed=0. `results.{1..8}.json` now present in `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-06-07T12:40:27.000Z

PRD_FINALIZED.md produced as a verbatim copy of PRD.md (byte-identical, `diff` reports no difference). Both Step 7 diff items are non-PRD-semantic, so no edits were warranted.

**Line counts:** PRD.md = 306; PRD_FINALIZED.md = 306. Delta 0 (0.0%).

**Why each Step 7 item is non-PRD-semantic:**
1. `test_03_scheduling_guards.py` adding `expected_status=201` to 8 dispatch-create assertions — pure test-assertion bug fix. PRD §4 already pins it: "Operations that create a new, stand-alone resource or append a new resource to a collection return a `201 Created` status code," and the §4 table lists `POST /dispatches` as a create. Impl already returns 201 (`routes/dispatches.py:122`). No PRD silence or mismatch.
2. `app.py`/`requirements.txt`/`start.sh` WSGI swap to waitress — pure infrastructure/transport fix; no observable request/response behavior change. PRD specifies business/API behavior, not WSGI server. Nothing to pin.

## Step 9: Complete PRD — 2026-06-07T12:47:53.000Z

Produced `workspace/PRD_COMPLETED.md` by copying `PRD_FINALIZED.md` and applying 8 minimal in-paragraph edits to pin implementation's actual behavior wherever PRD was silent or mismatched.

**Source vs completed:** Lines 306 → 306 (unchanged). Chars 42,341 → 44,114 (+1,773).
**Counts:** 6 ambiguity-pins, 2 mismatch-revisions.

**Per-change list:**
- §2.4 (Common Resource Properties) — insert — ambiguity — pinned `version` initial value to 1 — models.py:22
- §2.7 (Validation Ordering) — insert — ambiguity — pinned ownership-half of authz evaluated only after owned resource + intervening path ids resolve to exist, so not-found precedes ownership `ERR_FORBIDDEN_ROLE` — lookups.py:70-89, haul_jobs.py:187-189, invoices.py:57-59
- §2.7 (Validation Ordering, well-formedness) — insert — ambiguity — pinned required-field presence + identifier-field type validated before existence resolution; other type/enum/range/structural checks follow existence — dispatches.py:34-43, haul_jobs.py:30-33
- §3.1 (Configuration) — insert — ambiguity — pinned duplicate-email rejection `ERR_INVALID_REQUEST` + credit_limit_cents default 50000 — config.py:139, config.py:143-145
- §3.2 (Job Intake, items) — insert — ambiguity — pinned adding item to job not in DRAFT/ESTIMATED → `ERR_JOB_NOT_ESTIMATED`; `description` optional/null when omitted — haul_jobs.py:101-106
- §3.2 (Job Intake, photo-estimate) — insert — ambiguity — pinned `declared_items` entry `quantity` default 1 (min 1); omitted `declared_items` stored as empty array — haul_jobs.py:144-160
- §3.4 (Scheduling) — insert — ambiguity — pinned dispatch credit-limit exposure = job's `estimated_total_cents` (0 if unset) — dispatches.py:110-111
- §3.6 (On-Site Execution, load) — revise — mismatch — corrected ordering: `ON_SITE` check (`ERR_JOB_NOT_ON_SITE`) precedes `measured_truck_fraction` range check (`ERR_INVALID_FRACTION`) — haul_jobs.py:349-352
- §3.8 (Invoicing, dispute) — revise — mismatch — corrected ordering: `dispute_status==NONE` guard (`ERR_INVOICE_ALREADY_DISPUTED`) before `billing_status==ISSUED` guard (`ERR_INVOICE_NOT_ISSUED`) — invoices.py:62-65

**Left unchanged (already-pinned / no concrete claim to mismatch):** test-clock set-but-not-read by business logic (service_type + stored shift bounds drive same-day/shift); `submit_estimate` imposes no job-state guard and PRD asserts none; rounding, tiered-band, credit-limit (strict `>`), buffer (`gap >= buffer`), existence-ordering (§2.6) already match impl.

## Pipeline complete — 2026-06-07T12:47:53.000Z

All 9 steps done. Final state: 63/63 tests pass across an 8-round parallel stability sweep (`results.{1..8}.json` present). Artifacts: SCAFFOLD.yaml + 2 design files, PRD.md → PRD_FINALIZED.md (verbatim) → PRD_COMPLETED.md, test_helpers/ + test_suite/ (63 tests), workspace/implementation/ (41 endpoints, Flask + in-memory, waitress WSGI).
