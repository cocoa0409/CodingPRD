# Worklog — task_1526_egg_layer_operation_grading_plant

## Step 1: Create Task Directory — 2026-08-13T18:08:00.000Z

Pre-assigned by pipeline dispatcher: `tasks/task_1526_egg_layer_operation_grading_plant/` with `workspace/` subdirectory verified present and empty. Step 1 treated as DONE per instructions; no index scan performed, no other task directory touched.

Scenario: Egg Layer Operation & Grading Plant (Cal-Maine style layer farm): flock placement & age/lay-curve tracking, feed conversion & production cost per dozen, grading/candling & size distribution, cage-free/pasture claim & audit compliance, egg pricing formula & retailer contract, salmonella testing & environmental sampling, spent-hen disposition & flock turnover, pack date/shelf-life & recall traceability

Difficulty target: harder than expert level.

## Step 3: Copy Shared Files — 2026-08-13T18:08:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1526_egg_layer_operation_grading_plant/workspace/INSTRUCTION.md` (1424 bytes). Done early while Step 2 subagent runs (independent of scaffold output).

## Step 2: Generate Scaffold — 2026-08-13T19:23:00.000Z

All three scaffold artifacts are generated, validated, and lint-clean in `/home/ubuntu/github/CodingPRD/tasks/task_1526_egg_layer_operation_grading_plant/`.

### Lint verdict (verbatim)

```
Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     43
  Calls scanned (§1.8+§1.9):  626

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Counts

- **Entities: 13** (Farm, House, Flock, FeedDelivery, ProductionDay [immutable event], GradingRun, EggLot [cascade-born only], RetailerContract, Settlement, SalmonellaTest, ComplianceAudit, Recall, SpentHenDisposition)
- **State machines: 10** — including Flock (cyclic molt loop LAYING→MOLT_REST→LAYING with MAX_MOLTS cap), EggLot (parallel dimensions: lifecycle × hold), House (cyclic turnover), Contract (ACTIVE↔SUSPENDED cycle), plus branching Settlement/Recall/Audit machines
- **Calculations: 11** — lay-curve projection, FIFO feed costing (chronological), cost-per-dozen (ACTUAL_FIFO vs PROJECTED_STANDARD variants), settlement pricing (MARKET_INDEX vs COST_PLUS variants, pinned per-line rounding, pre-rebate tier selection), size-distribution materialization, shelf-life expiry, sampling cadence, two conservation invariants, compliance posture derivation
- **Validations: 12** priority tiers (auth → SoD → existence → schema → state → OCC → referential → safety → temporal → constraint → fiscal)
- **Endpoints: 64** (flat topology, `/_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z, daily ops-run checkpoint)
- **Errors: 29** (every one triggerable; all cross-referenced)
- **Roles: 6** (all opaque; segregation-of-duties model with two X-User-ID SoD pairs: grading submit≠confirm, test collect≠record-result)
- **§1.8 instances: 19** (all 9 rules ≥2; combinatorial_formula has 3 covering modes a/b/c)
- **§1.9 instances: 51** (43 active + 8 excluded_because stubs), across all 9 guide sections

### Notable design decisions

- **Complexity profile**: compliance_audit primary + pricing_engine secondary; layers = cascading_side_effects, dual_variant_calculation, ops_run_checkpoint, optimistic_concurrency. Flat topology (0%-in-examples pick) and self-referential `Flock.prior_flock_id` for flock turnover.
- **Layered interdependent calc chain**: age → lay-curve rate → projected eggs → projected vs FIFO-actual cost-per-dozen → COST_PLUS settlement price; every formula-derived assert literal was pre-computed by executing the formulas in Python (e.g., cpd 252.76 vs 251.86; MEDIUM line 137.75→138×24=3312 not 3306; rebate fixture subtotal 100920 lands post-rebate at 98902, *below* its own tier threshold — tier keyed on pre-rebate subtotal is falsifiably pinned).
- **Depth-4 transitive cascade**: POSITIVE test → flock QUARANTINED → lots HELD → contract auto-SUSPENDED (held_allocated_dozen>0) → DRAFT settlements VOIDED, plus auto-created Recall; the recall close runs the reverse leg (test RESOLVED, quarantine cleared, posture restored, contract reinstatable).
- **Two interval semantics for Rule 8**: half-open contract windows (touching legal) vs 30-day minimum-buffer audit calendar (touching illegal at 29 days).
- **Single OCC rule** (`settlement-create-stale-contract`) passing the serial-observability filter; deterministic two-sequential-request test.
- One adaptation during linting: the ProductionDay immutability corner was rewritten to assert the event-entity shape (no `version`/`updated_at`) rather than calling an undeclared PATCH route, since lint rule (a) forbids calls to non-existent endpoints even in negative tests.

Orchestrator verification: SCAFFOLD.yaml 1715 lines / SCAFFOLD_DIFFICULTY_DESIGN.yaml 1388 lines / SCAFFOLD_CORNER_DESIGN.yaml 1905 lines; all three parse as YAML; SCAFFOLD.yaml contains neither design key; design files carry their single top-level keys.

## Step 4: Generate PRD — 2026-08-13T19:55:00.000Z

Done. PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1526_egg_layer_operation_grading_plant/workspace/PRD.md` (the withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` were never opened; no sibling tasks were inspected).

### Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1526_egg_layer_operation_grading_plant/workspace/PRD.md` — 331 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context + design-principles angle)
- §2 Global Specifications: 2.1 RBAC, 2.2 API Response Structure (verbatim block, byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination and List Ordering, 2.4 The Logical Clock and the Daily Ops Run, 2.5 Common Resource Properties, 2.6 Units/Precision/Rounding, 2.7 Optimistic Concurrency Control, 2.8 Validation Order and Error Precedence (12 tiers), 2.9 Identifier Resolution, 2.10 Conserved Quantities (hen/egg ledgers, FIFO)
- §3 Business Logic (9 subsections): farm/house/placement, flock lifecycle + lay curve + molt, feed/production/economics, grading + lot materialization, lot journey (release/holds/allocate/ship/expiry), contracts + settlement pricing, salmonella testing + positive cascade, audits/posture/recalls, dispositions + house turnaround
- §4 Endpoint Definitions (64-row, 4-column table), §5 Error Code Catalogue (29-row, 2-column table)

**Coverage self-audit (per scaffold table):**
- **Entities:** 13/13 covered, including all 116 scaffold field names plus endpoint-only identifiers (`to_iso8601`, `current_utc`, ops-run counters, economics response fields, `variant`, `lines` sub-fields) — Contract 1 PASS: 138/138 required identifiers present in backticks, 0 missing (two-pass mechanical diff against the scaffold).
- **State machines:** 10/10 with every transition expressed — from/to states, actors, preconditions paired with error IDs, and all side effects (incl. Flock 7 transitions, House 5, GradingRun 5 with CONFIRMED-void compensation, EggLot 15 across the dual lifecycle/hold dimensions, RetailerContract 6, Settlement 2, SalmonellaTest 4, ComplianceAudit 4, Recall 2, SpentHenDisposition 2).
- **Calculations:** 11/11 with formulas, constants, rounding, and evaluation order in reconstructible prose — lay curve (ramp 18–20, plateau 21–30, 0.015/week decline with 0.40 floor, 0.85 post-molt factor, half-up 2dp, scaffold reference points verified), FIFO costing, FCR (60 g default, size weights 42–77 g, 3dp, null rule), cost-per-dozen both variants (420-day amortization, 115 g/hen-day, hen-day share, spent-hen credit), lot materialization (JUMBO→PEEWEE order, floor-by-12, mod-12 loose pool, 45/30/30 shelf life), settlement pricing (pinned 7-step order, per-line rounding, size/grade/claim multiplier, pre-rebate tiers 500000→0.04 / 100000→0.02), shelf-life expiry, sampling cadence (W1 weeks 40–45 pinned to placement+321 d, W2 post-molt weeks 4–6 pinned to molt+48 d), both balance invariants, posture derivation.
- **Validations:** 12/12 priority tiers expressed as an explicit ordered-precedence paragraph with error IDs and statuses; every tier's `applies_to` scope enumerated in the §3 workflow narratives.
- **Endpoints:** 64/64 in the §4 table with correct roles; all side effects rendered in §2/§3 prose.
- **Errors:** 29/29 in §5 with correct HTTP statuses (mechanical match), all 29 also named with trigger conditions in §2/§3 prose.
- **Roles:** 6/6 with exact spellings, opaque-identity prose, and the two SoD comparison exceptions.
- **Contract 3 (§3 path purity):** PASS — 831 backticked tokens scanned, 0 paths/methods.
- **Style checks:** no fuzzy/approximating words (the only "around" hits are the noun "turnaround"), no operator pseudocode leaks, all 37 state strings and all enum values present.

**Fixes applied during self-audit:** symmetric 30-day audit-gap phrasing, `ERR_VALIDATION` attached to future `placement_date`, per-lot/contract version increments added to the recall sweep, terminal markers added for `CLEARED`/`CLOSED_PASSED`/`CLOSED_FAILED`.

## Step 6: Generate Implementation — 2026-08-13T20:32:00.000Z

Implementation complete and verified. Summary below.

### Files delivered (all under `/home/ubuntu/github/CodingPRD/tasks/task_1526_egg_layer_operation_grading_plant/workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Guarded pip install (no-op when flask importable), `exec python3 app.py` foreground |
| `requirements.txt` | 1 | `flask>=3.0,<4.0` |
| `app.py` | 56 | App factory, blueprint registration, envelope error handlers (ApiError/404/405/500), `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 88 | In-memory stores (13 dicts, empty at boot), logical clock (default `2026-08-01T00:00:00Z`), seq/tick counters, `new_record`/`touch` |
| `errors.py` | 53 | All 30 PRD error IDs + `ApiError` |
| `response.py` | 96 | Envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, 1–100 clamp-reject), date serialization |
| `middleware.py` | 39 | Tier-1 auth (`X-User-ID`+`X-User-Role`, six roles) + tier-2 RBAC decorator |
| `util.py` | 164 | ISO date/instant parsing, Decimal round-half-up helpers, tier-5 field validators |
| `services/domain.py` | 326 | Lay curve, flock/contract/farm computed fields, sampling windows, posture derivation + SUSPENDED cascade |
| `services/pricing.py` | 161 | FCR (3dp), cost-per-dozen ACTUAL_FIFO / PROJECTED_STANDARD / farm-level for COST_PLUS finalize |
| `services/ops_run.py` | 153 | Daily ops run, pinned six-step order |
| `routes/core.py` | 133 | clock, ops, farms, houses (7 routes) |
| `routes/flocks.py` | 217 | flock CRUD + molt/resume/depopulate + economics (7 routes) |
| `routes/production.py` | 176 | feed deliveries + FIFO costing + production days (6 routes) |
| `routes/grading.py` | 353 | grading runs + egg lots incl. holds/allocate/ship (13 routes) |
| `routes/contracts.py` | 327 | contracts + settlements with OCC and pinned 7-step pricing (10 routes) |
| `routes/compliance.py` | 404 | salmonella tests + positive cascade, audits, recalls (16 routes) |
| `routes/dispositions.py` | 117 | spent-hen dispositions complete/void compensation (5 routes) |

**Total: 2,874 lines, 64 endpoints** (all 64 from the scaffold/PRD endpoint table).

### State machines implemented (9)
Flock (PLACED→GROWING→LAYING→MOLT_REST→LAYING loop, →DEPOPULATING→DEPLETED, plus quarantine parallel dimension), House (5-state turnaround cycle), GradingRun (DRAFT/SUBMITTED/CONFIRMED/VOIDED with confirmed-void compensation), EggLot (lifecycle × hold parallel dimensions), RetailerContract (DRAFT/ACTIVE/SUSPENDED/EXPIRED with DRAFT-settlement voiding cascades), Settlement (DRAFT/FINALIZED/VOIDED with supersession), SalmonellaTest (SCHEDULED→COLLECTED→RESULTED→CLEARED/RESOLVED; NEGATIVE auto-continues, version +2), ComplianceAudit (5 states with FAILED cascade), Recall (INITIATED→SCOPED→CLOSED), SpentHenDisposition (PLANNED/COMPLETED/VOIDED).

### Calculations implemented
Lay-curve projection (verified against all PRD reference points: 23.75 @18, 71.25 @20, 95.00 plateau, 93.58 @31, 52.25/44.41 @60, 50.83/43.20 @61, 38.00/32.30 floor @70 — single rounding after post-molt factor), feed FIFO costing (chronological, integer cents, exhaustion rejects with nothing consumed), FCR (3dp, null on zero egg mass, size-weighted avg from latest confirmed run), cost-per-dozen ACTUAL_FIFO and PROJECTED_STANDARD (hen-day share, 420-day amortization, spent-hen credit, 115 g/hen-day standard intake), size-distribution materialization (fixed JUMBO→PEEWEE order, mod-12 loose pool), settlement pricing (pinned 7-step order, per-line round-half-up to integer cents before summing, pre-rebate subtotal tier selection 500000→0.04 / 100000→0.02), shelf-life expiry (inclusive ship boundary), sampling cadence windows (W1 age 40–45 pinned at placement+321d; W2 post-molt weeks 4–6 pinned at molt+48d), compliance posture derivation (SUSPENDED/WATCH/CLEAR with 30-day failed-audit window and later-passed override), hen and egg conserved ledgers (computed on read → void compensation is exact by construction).

### Logical clock and ops run
Clock lives in a module-global; startup default exactly `2026-08-01T00:00:00Z`; `POST /_clock/set_current_utc` (PlatformAdmin) parses any ISO 8601 instant and echoes the raw string as `current_utc`. All domain dates compare against the clock's date; `created_at`/`updated_at`/`api_request_timestamp` format the clock with 3 fractional digits. The ops run executes the six steps in the pinned order (lots → contracts → flocks → houses → sampling → postures) with the specified sort orders and returns the five counters; every mutated entity gets its own version bump.

### Verification
Three ad-hoc suites run against live boots: 88 + 60 + 4 checks, all passing — covering auth tiers, RBAC, SoD pairs, all cascades (hold→suspend→void-settlements, POSITIVE six-link cascade with auto-recall, audit-FAILED, depopulation→depletion→house turnaround, void compensation, expiry, supersession), OCC 412, claim dominance, window overlap/touching, 30-day audit gap, 7-day sampling gap, shelf-life boundary equality, economics numbers (111.50 projected, 8106.67 actual, FCR 20.263), pagination meta, and reboot-clean empty store.

### PRD/scaffold discrepancies and judgment calls
- **Validation precedence**: PRD §2.8's 12 tiers win over scaffold state-machine precondition listing order (e.g., induce-molt checks quarantine (tier 9) → age (tier 10) → molt cap (tier 11), not the scaffold's age-first listing; allocate checks contract-active (tier 8) before hold/claim (tier 9) before volume (tier 12)).
- **NEGATIVE result version**: scaffold lists `RESULTED→CLEARED` as its own +1 transition inside the record-result request, so a NEGATIVE recording nets version +2 (implemented as written).
- **Economics missing query params**: PRD marks `period_start`/`period_end` optional but defines no defaults; missing/invalid → `ERR_VALIDATION` 400; `variant` defaults to `ACTUAL_FIFO`.
- **COST_PLUS settlement base**: §3.3 is written per-flock; for finalize I generalized to farm-level ACTUAL_FIFO (all farm flocks' production days, share=1, per-flock amortization summed) — the only reading consistent with a farm-scoped contract.
- **Duplicate `house_code`**: uniqueness stated but no error ID assigned; returned `ERR_VALIDATION` 400.
- **Pre-finalize settlement fields** (`pricing_model_used`, `lines`, totals, `scoped_lot_count`, audit findings): serialized as `null`/`[]` until computed.
- **Auto-recall pack window with zero held lots**: falls back to clock date for both bounds (PRD silent).
- **Missed-window WATCH** is evaluated for LAYING flocks (matching the scheduler's input set; PRD is ambiguous for depopulated flocks).

## Step 5: Generate Unit Tests — 2026-08-13T20:45:00.000Z

Note: the Step 5 subagent's first run truncated mid-generation (test_helpers incomplete, test_suite empty); the orchestrator resumed it via SendMessage and it completed the full generation. Final report verbatim:

Generation complete and all verification stages pass. Summary:

### Output

**`test_helpers/` (9 modules)** — `/home/ubuntu/github/CodingPRD/tasks/task_1526_egg_layer_operation_grading_plant/test_helpers/`
- `types.py` — 11 status enums + role enum + 13 entity TypedDicts; `ProductionDay` correctly omits `updated_at`/`version` (common_fields: false, PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (44 endpoints incl. `/_clock/set_current_utc` and `/api/ops/run-daily`)
- `api_errors.py` — 29 `ApiErrorId` members + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserters, `assert_calendar_date`, `assert_hen_ledger`
- `factories.py` — 14 payload factories, input fields only
- `constants.py` — lay-curve/FIFO/shelf-life/rebate/cadence thresholds from PRD §2–§3
- `test_users.py` — six opaque role header constants + `make_role_headers` (used for SoD same-operator pairing)
- `fixtures.py` — composite chains: farm/house/flock hierarchy, LAYING state progression, production-day recording, grading confirm, active contracts, release→allocate→ship, draft settlements (reads fresh contract version for OCC), collected salmonella tests, audit walks, depopulation/depletion, clock/ops drivers

**`test_suite/` (13 test files + conftest.py, 84 tests)** — `/home/ubuntu/github/CodingPRD/tasks/task_1526_egg_layer_operation_grading_plant/test_suite/`
- Queue A (Difficulty): **40 tests** across all 19 instances (17 instances × 2 + 2 dual-variant instances × 3)
- Queue B (Corner): **44 tests** across all 43 non-stub instances (42 × 1 + sampling-cadence instance × 2 for the 4-day/7-day boundary pair)

### Verification results
- All files compile; `pytest --collect-only` collects 84 tests cleanly with framework imports resolved
- Tag audit: every test ends with exactly one `Design: …` line; all 84 tags resolve to real instances; every difficulty instance has ≥2 tests; every non-stub corner instance has ≥1; all 8 `excluded_because:` stubs (errors section) have valid difficulty cross-references and were NOT translated
- Citation audit: all 152 quoted PRD passages verified verbatim against PRD.md (≥8-word grep window)
- No `skip`/`skipif`/`xfail`, no scaffold references in comments/docstrings

### Instances skipped
None. All 19 difficulty instances and all 43 non-stub corner instances passed the PRD-first two-condition filter — the PRD is unusually precise (pins all numeric examples, tier priorities, cascade links, and boundary inclusivity in prose).

### Notes / minor PRD observations
- The PRD never pins the initial `version` value of a newly created resource (§2.5 only pins "+1 per modification"). The `farm_creation_defaults_and_envelope` instance's `version == 1` literal is therefore asserted as field presence/type (`isinstance(int)`) rather than the literal — the uniquely-derivable portion of that claim.
- Generation bug caught and fixed during self-review: the FCR test's 120 kg feed issuance requires pre-stocked FIFO deliveries (added), otherwise setup would hit `ERR_FEED_STOCK_EXHAUSTED`.

## Step 7: Test/Iterate Loop — 2026-08-13T20:55:00.000Z

All 8 parallel rounds passed with `passed == total` (84/84 in every round, zero failures in the union). The exit condition is met on the first iteration — no diagnosis or fixes were needed.

### Summary

- **Iterations run:** 1 (the initial 8-round parallel stability sweep; all 8 rounds ran to completion under `--isolation per-test-server`).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:** none.

**Result details:** Each of the 8 rounds reported `passed=84, total=84, failed=0`, and a per-test status audit of all eight `results.{1..8}.json` files confirmed every one of the 84 tests in `passed` status in every round — no flaky or round-dependent behavior whatsoever. The existing implementation in `workspace/implementation/` (Flask app with in-memory dict storage, logical clock defaulting to `2026-08-01T00:00:00Z`, six-step pinned daily ops run, conserved hen/egg/feed ledgers, SoD pairs, OCC on settlement creation, and the full §5 error catalogue) is fully consistent with the test suite as written.

Orchestrator verification: independently re-read all 8 `results.{1..8}.json` files — every round reports 84/84 passed, 0 failed.

## Step 8: Finalize PRD — 2026-08-13T20:55:30.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline, so `PRD.md` already determined every behavior the implementation exhibits. No `PRD_FINALIZED.md` is produced; Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-08-13T21:05:00.000Z

PRD_COMPLETED.md is complete. All edits verified against the actual code.

### Exit summary

- **Files**: `workspace/PRD.md` (331 lines, 69,448 chars) → `workspace/PRD_COMPLETED.md` (331 lines, 72,040 chars; **+2,592 chars, +0 lines** — all edits are in-paragraph).
- **Counts**: 18 ambiguity-pins, 0 mismatch-revisions. All 9 flagged judgment calls (a)–(i) were confirmed in code and pinned; 9 further underdetermined behaviors were found and pinned. No impl behavior contradicted PRD prose outright.

Changes (all `insert`/`revise` inline, no new sections):

- §2.3 — insert — ambiguity — out-of-range/non-integer `limit` or negative `offset` rejected with `ERR_VALIDATION` 400, never clamped — response.py:45-67
- §2.4 — insert — ambiguity — ops-run summary counters count mutated entities, not transitions (double-advanced flock counts once in `flocks_advanced`) — services/ops_run.py:64-78
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — db.py:68-79
- §2.5 — insert — ambiguity — not-yet-assigned fields serialize as `null` (grading-run counts/`submitted_by`/`confirmed_by`/`pack_date`, test `collected_*`/`result`/`resulted_by`, disposition `completed_date`, recall `scoped_lot_count`, draft settlement pricing fields) and list fields (`lot_ids`, `lines`) as `[]` — grading.py:79-93, compliance.py:58-62/175, contracts.py:218-224
- §3.1 — insert — ambiguity — duplicate `house_code` within a farm → `ERR_VALIDATION` 400 — routes/core.py:99-101
- §3.1 — insert — ambiguity — `initial_hen_count` over house capacity → `ERR_VALIDATION` 400 (not `ERR_HEN_COUNT_EXCEEDED`) — routes/flocks.py:61-63
- §3.3 — insert — ambiguity — economics `variant` defaults to `ACTUAL_FIFO`; unrecognized variant or missing/malformed `period_start`/`period_end` → `ERR_VALIDATION` 400 — routes/flocks.py:189-199
- §3.3 — insert — ambiguity — FCR average egg weight stays at 60 g when the latest confirmed run's six size-class counts total zero — services/pricing.py:63-64
- §3.3 — insert — ambiguity — `lay_date` before placement or after clock date → `ERR_VALIDATION` 400 — routes/production.py:100-103
- §3.6 — insert — ambiguity — `effective_start` not preceding `effective_end` → `ERR_VALIDATION` 400 — routes/contracts.py:76-77
- §3.6 — revise — ambiguity — `market_index_cents` on a `COST_PLUS` contract is validated as a non-negative integer and stored, but unused in pricing — routes/contracts.py:190-192,215
- §3.6 — revise — ambiguity — `COST_PLUS` base is the `ACTUAL_FIFO` cost per dozen computed at **farm level** (eggs/feed/credit aggregated over all the farm's flocks, overhead at share 1, amortization summed over all flocks) — routes/contracts.py:280-284, services/pricing.py:147-161
- §3.7 — insert — ambiguity — NEGATIVE auto-continuation RESULTED→CLEARED is a second transition; version +2 in one request — routes/compliance.py:134-139
- §3.7 — insert — ambiguity — auto-created recall pack window is earliest→latest held-lot `pack_date`, falling back to the clock date for both bounds when no lots were held — routes/compliance.py:162-166
- §3.8 — insert — ambiguity — recall pack window start-after-end → `ERR_VALIDATION` 400 — routes/compliance.py:309-310
- §3.8 — revise — ambiguity — "later audit closed PASSED" is judged by close-operation order, not `closed_date` — services/domain.py:296-302, routes/compliance.py:284-285
- §3.8 — revise — ambiguity — missed-sampling-window WATCH evaluated only for flocks currently `LAYING` — services/domain.py:309-311
- §3.8 — insert — ambiguity — posture recomputation rewrites stored `compliance_posture` without incrementing the farm's `version` or refreshing `updated_at` — services/domain.py:316-326

Tests were used only as a cross-reference (they assert none of the above points contradictorily); implementation was the sole alignment target.
