# Worklog — task_1678_heat_treating_service

## Step 1: Create Task Directory — 2026-08-14T06:47:00.000Z

Pre-assigned directory `tasks/task_1678_heat_treating_service/` with `workspace/` subdirectory confirmed to exist. Step 1 treated as DONE per pipeline instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T07:43:00.000Z

All three scaffold artifacts are generated, validated, and lint-clean.

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1678_heat_treating_service/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`, 18 instances (2 per each of the 9 rules)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`, 39 instances (active + `excluded_because` stubs)

**Design summary:**
- **Profile**: compliance_audit primary + posture_driven_gating secondary; flat topology (all FK reverse-reachability via filtered-list GETs), parallel state dimensions on WorkOrder (processing_status × quality_status), segregation_of_duties role model (disposition decider ≠ inspection recorder; QE compiles vs NadcapAuditor issues audit packages), immediate consistency.
- **Surface**: 12 entities (CustomerAccount, FurnaceRecipe, Furnace, PyrometryRecord, WorkOrder, LoadBatch, LoadAssignment, LoadThermocoupleReading, InspectionTest, DispositionCase, LiabilityClaim, AuditPackage), 45 endpoints, 44 error codes, 7 roles (Customer is `entity_backed:CustomerAccount`, rest opaque).
- **Key mechanics**: derived Furnace qualification posture (AMS2750 TUS/calibration intervals per class) gating load release/start; OCC on `LoadBatch.version` for assignment writes (412 ERR_STALE_VERSION); dual-variant liability payout (3× charge vs 85¢/lb by tier: 300000 vs 85000 for identical inputs); provisional-vs-final rush surcharge with breach waiver (35000 → 0); pinned round-per-order-then-sum energy settlement (3992 vs 3991); re-treat cycle with `retreat_count == max_retreats` boundary; buffered quench-purge adjacency (60 min, different media) vs pyrometry validity containment (two distinct interval semantics); 4-hop SCRAP cascade (case → WO → claim → customer exposure) and FAIL-survey HOLD/re-qualify cascade; logical-clock endpoint with the mandated `2026-08-01T00:00:00Z` default.

**Verification**: `scaffold_lint.py` verdict — clean lint (620 calls scanned, 0 violations; all FKs reverse-reachable). Additionally checked: instance-name uniqueness across both design files (72 names, no dupes), all `excluded_because` stubs resolve to real difficulty instances, 2 instances per difficulty rule, and no forbidden concurrency vocabulary (one "in parallel" phrase was found and reworded).

## Step 3: Copy Shared Files — 2026-08-14T07:44:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1678_heat_treating_service/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T08:03:00.000Z

All three hard contracts now verify clean. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1678_heat_treating_service/workspace/PRD.md`.

## Summary

Generated the PRD for `task_1678_heat_treating_service` from `SCAFFOLD.yaml` per the `prd-bench-doc-generator` skill. The two difficulty-design YAMLs were not opened or referenced.

**Document design** (domain-derived, not template-copied):
- §1: two-paragraph introduction from the commercial heat-treating trust/audit angle.
- §2: ten subsections — RBAC (with per-role identity semantics: `Customer` entity-backed, six opaque roles), verbatim §2.2 response structure, pagination (with the filter enumeration), common resource properties (including the reduced `id`+`created_at`-only set for the three append-only entities), the logical clock (startup default 2026-08-01T00:00:00Z, `to_iso8601`), precision conventions, furnace qualification posture (derived, with BUILDING↔HOLD cascades), the 10-tier validation pipeline order, OCC on load builds, and nested-resource retrieval.
- §3: nine subsections organized along the shop's business timeline — accounts/credit, recipes/furnaces, pyrometry & posture derivation, intake & rush pricing, load build/release gating, run/complete/abort with energy settlement, inspection & disposition, shipping/cancellation/claims, and Nadcap audit packages. All constants embedded in prose (15,000¢ base, 20%, 24h/1.5× expedite, 25,000¢/200,000¢ clamp, 3× charge vs 85¢/lb tiers, 30/60/90/180-day TUS intervals, 60-minute purge gap, 133¢/lb energy rate with pinned per-order rounding).
- §4: 45-row endpoint table (4 columns only); §5: 44-row error table (2 columns only).

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 75 required, 75 present, 0 missing
- endpoints[].request_body: 49 required, 49 present, 0 missing
- endpoints[].query_params: 13 required, 13 present, 0 missing
- endpoints[].path_params: 12 required, 12 present (inside backticked §4 paths), 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 10 tiers expressed in fixed pipeline order in §2.8 (incl. masking example), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (assign + unassign, expected_load_batch_version, ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all 9 state machines expressed (from/to states, precondition→error_id pairs, side-effect cascades), 0 missing
- calculations[]: 8 checked, 8 fully expressed in precise prose (no pseudocode, no fuzzy wording), 0 missing
- validations[] conditions: 44/44 error IDs matchable to trigger conditions in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all 45 endpoints' side effects and scoped rule applications expressed, 0 missing
- entities[].fields[] structured content: defaults, nulls, enums (52/52 values), and reduced common-fields for append-only entities all reconstructible, 0 missing
- sibling-branch symmetry: RE_TREAT/SCRAP/RETURN_AS_IS, accept/pay/reject, STANDARD/EXTENDED payout variants, provisional/final surcharge variants all at equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 399
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 block is byte-identical to `section-2.2-response-structure.md`, and §4/§5 tables are complete against the scaffold (45 endpoints, 44 errors).

## Step 6: Generate Implementation — 2026-08-14T08:50:00.000Z

All 59 tests pass (0 failed/errors/skipped) under the exact harness mode `prd-bench-local-run --isolation per-test-server`, which restarts the server via `start.sh` before every test. Full run: 77s.

## Report

**Delivered**: complete Python + Flask implementation in `/home/ubuntu/github/CodingPRD/tasks/task_1678_heat_treating_service/workspace/implementation/`.

**Structure**:
- `start.sh` — guarded pip install (no-op once flask is importable), `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — entry point, global request lock, error handlers, blueprint registration
- `db.py` — empty-per-boot in-memory store (no seeding), logical clock (default exactly `2026-08-01T00:00:00Z`), wall-clock 3-fractional-digit `created_at`/`updated_at`, logical-clock ISO formatting (no fractional part when zero)
- `response.py` — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; errors carry `data.error_id`/`data.message`; list meta adds `limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamped 1–100)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), 7-role RBAC (403 `ERR_INSUFFICIENT_PERMISSIONS`), Customer ownership scoping (403 `ERR_OWNERSHIP_MISMATCH`)
- `validation.py`, `errors.py`
- `services/domain.py` — all calculations in `Decimal` with `ROUND_HALF_UP`: rush quote (15,000 + 20% charge, ×1.5 expedite ≤24h, clamp [25,000, 200,000]), dual-variant liability payout (STANDARD 3× charge vs EXTENDED 85¢/lb, round-then-cap), per-order-line energy settlement at 133¢/lb (round-then-sum), pyrometry intervals (30/60/90/180-day TUS by class, 90-day calibration), derived furnace posture with pinned precedence and BUILDING↔HOLD cascades, schedule overlap + 60-minute quench purge-gap gates, pyrometry-window containment
- `routes/` — all 45 endpoints: customers, recipes (+approve), furnaces, pyrometry, work orders (+ship/cancel), inspection tests, disposition cases (+decide), liability claims (+accept/reject/pay), load batches (+assignments/unassign OCC-guarded with `expected_load_batch_version` → 412 `ERR_STALE_VERSION`, release/start-run/complete-run/abort), thermocouple readings, audit packages (+issue), `_clock/set_current_utc`

**Key fidelity points honored**: 10-tier validation pipeline order (state-beats-safety, existence-beats-temporal/fiscal verified by tests); posture recomputed on furnace read / pyrometry create / release / start-run with lazy recompute after clock set; append-only evidence entities expose only `id` + `created_at`; inclusive hardness/distortion bands; strict-greater breach and excursion semantics; re-treat ceiling `retreat_count == max_retreats`; segregation of duties on disposition decide; Customer-entity-backed ownership on the three scoped endpoints; computed-field client input ignored.

(Note: Step 6 ran concurrently with Step 5; its self-check ran against the test suite files present at that moment. The authoritative pass/fail loop is Step 7.)

## Step 5: Generate Unit Tests — 2026-08-14T08:52:00.000Z

Generation complete. Summary of what was produced:

## Stage 1 — `test_helpers/` (9 files)

- `types.py` — 7 roles, 15 status/enum types, 12 entity TypedDicts; the three append-only evidence records (PyrometryRecord, LoadThermocoupleReading, InspectionTest) correctly omit `updated_at`/`version` per PRD §2.4.
- `api_client.py` — `ApiClient(GenericApiClient)` with all 45 endpoints (no `/api` prefix; `api_prefix: ""`), including `POST /_clock/set_current_utc`.
- `api_errors.py` — all 44 error IDs with the §5 status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions; append-only entities assert `updated_at`/`version` are **absent**; `assert_instant_equals` compares clock-valued fields by parsed instant (PRD pins the instant, not the string format).
- `factories.py`, `constants.py` (all pricing/pyrometry/energy/purge constants), `test_users.py` (opaque roles + `make_customer_headers` for the entity-backed Customer role; qe-1/qe-2 pair for segregation of duties), `fixtures.py` (~30 composite helpers: `setup_shop`, `qualify_furnace`, `assign_order` with auto OCC version refresh, `run_load_to_completed`, `process_order_to_processed`, `setup_failed_order`, `setup_scrapped_order`, `retreat_order_once`).

## Stage 2 — `test_suite/` (conftest + 10 files, 90 collected items)

75 test functions, each tagged with exactly one verbatim `Design:` line:

- **Queue A (difficulty):** all 18 instances × 2 tests = 36 tests — dual liability tiers (300000 vs 85000 + cap/rounding), rush provisional-vs-final breach/settle, clamp trio + ceiling/expedite boundary, energy round-per-line (3992 vs 3991 + half-up 199.5→200), re-treat cycles, complete/abort divergence, 4-hop scrap cascade + reject compensation, FAIL/clock-driven HOLD↔BUILDING cascades, both priority pairs (state>safety, existence>temporal/constraint), weight and re-treat boundaries (incl. fractional 999.999+0.001), both cross-entity gates, purge-gap/window-containment interval semantics (incl. 60-min-exact and start-at-performed_at edges), assign/unassign and claim pay/reject invariants.
- **Queue B (corner):** all 39 non-stub instances × ≥1 test; all 15 `excluded_because:` stubs left untranslated with cross-references verified to resolve.

## Verification performed

- Tag audit: 18/18 difficulty instances ≥2 tests, 39/39 non-stub corner instances ≥1 test, no dual/unknown/stub tags.
- Citation audit: every docstring contains a ≥8-word verbatim substring that literally greps `workspace/PRD.md`.
- `pyflakes` clean; `pytest --collect-only` collects 90 items with no import errors; no skip/xfail markers; no scaffold references in comments/docstrings.

One deliberate adjudication: initial `version == 1` is not uniquely derivable from the PRD (§2.4 pins only "increments on every mutation"), so all version assertions are relative to the create-response version rather than absolute — preserving the two-reader property without weakening any PRD-pinned claim.

## Step 7: Test-Fix Loop — 2026-08-14T09:05:00.000Z

**Summary**

- **Iterations run**: 3 sweeps of 8 parallel rounds each (initial + 2 fix-verification rounds). Final sweep: **90/90 passed in all 8 rounds, 0 failed, 0 errors** — deterministic green.
- **Tests deleted**: none. All 3 failing tests traced to PRD-verbatim rules; no deletions were warranted.
- **Fixes applied to `test_helpers/`**:
  - `fixtures.py` / `setup_scrapped_order` — the fixture accepted `customer_overrides` as a named parameter but never forwarded it into the `setup_failed_order` chain, so `liability_tier: "EXTENDED"` silently fell back to the STANDARD default and the payout computed as `min(100000, 3×100000) = 100000` instead of the EXTENDED `round_half_up(85 × 10.005) = 850`. Added `customer_overrides=customer_overrides` to the forwarded call. (Four other callers passed STANDARD overrides, which is why the swallow was invisible elsewhere.)
- **Fixes applied to `test_suite/`** (both are STEP-2 test-setup bugs — fixtures violated PRD-pinned preconditions the implementation correctly enforces):
  - `test_08_inspection_and_disposition.py::test_inspection_fail_creates_open_disposition_case` — called `process_order_to_processed()` twice; the second shop re-used the factory's default `(alloy_code=4140, spec_code=AMS2759)` and `furnace_code=F-1`, tripping PRD §3.2's verbatim uniqueness rules ("the pair must be unique across all recipes … `ERR_DUPLICATE_RECIPE`", "registers each Furnace with a unique `furnace_code`"). Gave the second shop `alloy_code=8620` / `furnace_code=F-2` (the same explicit-override pattern `test_10` already uses).
  - `test_09_shipping_and_turnaround.py::test_rush_final_settles_quote_when_guarantee_met` — identical duplicate-shop pattern (`_setup_shippable_rush_order` + a second `process_order_to_processed()`); same fix.
- **Fixes applied to `implementation/`**: none. The implementation's uniqueness enforcement (409 `ERR_DUPLICATE_RECIPE`, 400 `ERR_INVALID_REQUEST` on duplicate `furnace_code`) and its STANDARD/EXTENDED liability payout math were correct per PRD throughout; every failure was a test-artifact bug.

Files touched:
- `/home/ubuntu/github/CodingPRD/tasks/task_1678_heat_treating_service/test_helpers/fixtures.py`
- `/home/ubuntu/github/CodingPRD/tasks/task_1678_heat_treating_service/test_suite/test_08_inspection_and_disposition.py`
- `/home/ubuntu/github/CodingPRD/tasks/task_1678_heat_treating_service/test_suite/test_09_shipping_and_turnaround.py`
- `/home/ubuntu/github/CodingPRD/tasks/task_1678_heat_treating_service/worklog.md` (Step 7 entry)

## Step 8: Finalize PRD — 2026-08-14T09:10:00.000Z

`PRD_FINALIZED.md` is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1678_heat_treating_service/workspace/PRD_FINALIZED.md` with exactly one minimal inline revision.

## Exit summary

**Line counts**: PRD.md = 277 lines; PRD_FINALIZED.md = 277 lines (0.0% line-count delta; one sentence revised in place, ~30 words inserted).

### Changes (one bullet per change)

- **§3.2 (Process Recipes and Furnace Registration)** — revise — pinned the previously unspecified rejection for a duplicate `furnace_code` at furnace registration: inserted "— a duplicate `furnace_code` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) —" into the registration sentence — `implementation/routes/furnaces.py:29-31`.

### Items examined with no edit warranted

- **`test_helpers/fixtures.py` `customer_overrides` forwarding** — pure test-helper bug (parameter swallowed before `setup_failed_order`). The behavior it exposed (STANDARD payout `min(declared_value_cents, 3×processing_charge_cents)`; EXTENDED payout `min(declared_value_cents, round_half_up(85 × received_weight_lb))`) is already pinned verbatim in PRD §3.8 and matches `implementation/services/domain.py:71-76` exactly (constants `STANDARD_LIABILITY_MULT=3`, `EXTENDED_RATE_CENTS_PER_LB=85`, `_cents` = ROUND_HALF_UP at `domain.py:25-27,42-44`).
- **Duplicate `(alloy_code, spec_code)` → 409 `ERR_DUPLICATE_RECIPE`** — pinned verbatim in PRD §3.2; matches `implementation/routes/recipes.py:23-27`. Its tier-7-before-tier-9 ordering is already pinned by PRD §2.8.
- Both `test_suite/` fixes were test-setup violations of PRD-pinned preconditions; no implementation divergence.

### Per-edit pre-edit search log

**Edit 1 (§3.2 duplicate `furnace_code` clause):**
- (a) Subject: error identity/status for registering a Furnace whose `furnace_code` already exists.
- (b) Impl paths enumerated: `grep -rn "furnace_code"` across `implementation/**.py` returned exactly four hits — `routes/furnaces.py:20` (tier-9 `req_string`), `:29-31` (the sole uniqueness check, raising `ApiError("ERR_INVALID_REQUEST", 400)`), `:34` (field storage); PRD §4 endpoint table confirms no furnace-update route exists, so creation is the only path that can set the code. Also verified test_suite/test_helpers references (`test_02`, `test_03`, `test_08`, `test_09`, `factories.py`) assert nothing contradicting 400/`ERR_INVALID_REQUEST`, and that the uniqueness check and all neighboring field/enum checks raise the *same* error id and status, so check ordering is unobservable.
- (c) Wording adjustment: kept the clause an under-determined parenthetical that names only error id + HTTP status, deliberately silent on validation-pipeline position (any ordering yields identical observable behavior since all candidate checks emit `ERR_INVALID_REQUEST`/400), and scoped by the document's standing §2.8 convention — mirroring the existing recipe-uniqueness phrasing style rather than adding a new universal claim.

## Step 9: Complete PRD — 2026-08-14T09:25:00.000Z

The diff is exactly the intended minimal patch. All 90 tests in the last recorded run pass against this implementation, and every edit is inline (no new sections). Final verification of one detail — the §2.2 insert placement renders as its own paragraph before the §2.3 heading, confirmed in the diff.

## Summary

**Source:** `/home/ubuntu/github/CodingPRD/tasks/task_1678_heat_treating_service/workspace/PRD_FINALIZED.md` (existed; copied to `PRD_COMPLETED.md`)

**Line/char counts:** PRD_FINALIZED.md 277 lines / 40,477 chars → PRD_COMPLETED.md 280 lines / 42,584 chars (**+3 lines, +2,107 chars**)

**Change counts:** 18 total — **16 ambiguity-pins** (PRD silent), **2 mismatch-revisions** (PRD pinned a different behavior than impl). 2 pure inserts (new sentence; new table row), 16 in-paragraph revisions. Impl files referenced are under `/home/ubuntu/github/CodingPRD/tasks/task_1678_heat_treating_service/workspace/implementation/`.

- §2.1 — revise — ambiguity — whitespace-only header values count as empty; an `X-User-Role` outside the seven roles is rejected with `ERR_INSUFFICIENT_PERMISSIONS` on every endpoint — middleware.py:23, 31-38
- §2.2 — insert — ambiguity — undefined route or unsupported method is rejected with `ERR_NOT_FOUND` (HTTP 404) in the standard error envelope — app.py:35-43
- §2.3 — revise — ambiguity — `limit` clamped to [1,100] and `offset` to ≥0; non-integer values fall back to defaults (10/0) — response.py:62-72
- §2.4 — revise — ambiguity — `updated_at` equals `created_at` at creation; `version` starts at 1 — db.py:92-104
- §2.5 — revise — ambiguity — clock endpoint accepts any target instant (forward or backward); setting the clock does not itself recompute postures — the new instant takes effect at the next §2.7 recomputation point — clock.py:12-20, services/domain.py:139-172
- §2.6 — revise — **mismatch** — datetime comparisons evaluate the exact parsed instants with no truncation (PRD had claimed "second precision"; impl compares full-precision datetimes) — db.py:74-89, services/domain.py:150-153/213, routes/work_orders.py:123
- §2.9 — revise — ambiguity — omitting `expected_load_batch_version` is rejected with `ERR_INVALID_REQUEST` (400); the staleness comparison applies when the supplied value is an integer — routes/loads.py:19-24, 137-138, 180-181
- §3.2 — revise — ambiguity — `hardness_min_hrc`/`hardness_max_hrc` are whole-number HRC values (impl requires integers) — routes/recipes.py:40-41
- §3.3 — revise — ambiguity — `instrument_id` reads back as null when omitted on surveys — routes/pyrometry.py:29, 39
- §3.4 — revise — ambiguity — `guaranteed_turnaround_hours` is in whole hours (integer; non-integers fail `ERR_INVALID_REQUEST` before the window check) — routes/work_orders.py:47
- §3.4 — revise — ambiguity — a `guaranteed_turnaround_hours` supplied on a `STANDARD` order is ignored; the stored field reads null — routes/work_orders.py:68
- §3.5 — revise — ambiguity — abutting windows (one ends exactly when the other begins) are not overlapping and are permitted (strict-inequality overlap test) — services/domain.py:186
- §3.5 — revise — ambiguity — unassigning an assignment that is no longer `ACTIVE` is rejected with `ERR_INVALID_REQUEST` — routes/loads.py:182-183
- §3.5 — revise — **mismatch** — pyrometry containment permits `scheduled_end_at` equal to `next_due_at` ("on or before"; PRD had said strictly "before"; impl rejects only `end > next_due_at`) — services/domain.py:213
- §3.7 — revise — ambiguity — a new DispositionCase carries `decision` and `decided_by_user_id` null until decided — routes/inspections.py:62-69
- §3.9 — revise — ambiguity — manifest `load_batch_ids` echoes the submitted array; `pyrometry_record_ids` in record creation order; `thermocouple_reading_counts` is an object mapping load id → count; empty `load_batch_ids` is permitted and yields an empty manifest — routes/audit_packages.py:38-59
- §4 intro — revise — ambiguity — request-body fields beyond those named for an operation, including server-managed computed fields such as `outstanding_liability_exposure_cents`, are ignored — validation.py:8-15
- §5 — insert — ambiguity — added `ERR_NOT_FOUND | 404 Not Found` row to the error catalogue (companion to the §2.2 pin) — app.py:35-43

**Key findings:** The two real mismatches were (1) the §2.6 "second precision" claim vs. impl's exact-instant datetime comparisons, and (2) the §3.5 release containment end-boundary, where PRD said strictly "before `next_due_at`" but impl permits equality. Everything else was PRD silence over impl behavior (pagination clamping, OCC field typing, clock-set laziness, manifest shapes, ignored computed fields, etc.). All other PRD-pinned behaviors — rush quote formula, liability tiers, energy surcharge round-per-line, posture derivation and HOLD cascades, pipeline ordering, state machines — match the implementation exactly as written.
