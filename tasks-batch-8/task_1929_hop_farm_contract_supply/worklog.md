# Worklog — task_1929_hop_farm_contract_supply

## Step 1: Create Task Directory — 2026-08-15T01:23:00.000Z

Task directory `tasks/task_1929_hop_farm_contract_supply/` and `workspace/` pre-created by the pipeline launcher (Step 1 marked ALREADY DONE in the invocation args); verified both exist and are empty before proceeding.

## Step 2: Generate Scaffold — 2026-08-15T01:50:00.000Z

All audits pass. The scaffold package is complete and lint-clean.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1929_hop_farm_contract_supply/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (scenario verbatim, envelope, complexity profile, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, roles)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design:`

**Counts**: 11 entities · 9 state machines (incl. PelletLot's parallel `inventory_status` × `age_class` dimensions as two entries) · 9 calculations · 13 validation rows · 56 endpoints · 24 errors · 4 roles · §1.8: 18 instances (9 rules × 2) · §1.9: 52 instances (43 active + 9 `excluded_because:` stubs). All 24 error codes are exercised by at least one instance; all enum states are produced by a transition; 70 instance names unique across both design files.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (671 calls scanned.)

**Key design decisions**:
- **Archetype**: quota/allocation (pro-rata shortfall across multi-year contracts) with pricing-engine secondary (alpha-acid adjustment); flat topology, cyclic state shape, segregation-of-duties role model (claim filer's opaque `X-User-ID` cannot review/decide/pay the same claim).
- **Dual-variant calcs on different domains**: provisional-vs-final alpha pricing (Allocation) and projected-vs-actual indemnity (InsuranceClaim). Combinatorial modes: branched price formula with min-price floor (mode a) and pinned aggregate-then-round pellet blending (mode b; 104+104 dried lbs → 191, not 192 per-lot).
- **Cascades**: lab-FINAL regrade chain LabTest→HarvestLot→PelletLot→Allocation (depth 3); settle-shortfall chain Allocation→Contract (consecutive-shortfall counter hits 2 → DEFAULTED)→sibling Allocation CANCELLED (depth 3, different trigger).
- **Reservation model**: allocation confirm FIFO-reserves whole pellet lots (entered_storage_at ASC, created_at ASC tie-break); delivery consumes the reserved set — this makes confirm/cancel a clean compensating invariant and gives terminate/default cascades a physical release step.
- **Temporal overlap on two resources with different semantics**: discrete (field, crop_year) season slots vs continuous kiln windows with a symmetric 30-minute buffer (20-min gap rejected, exactly-30 accepted).
- **Logical clock** `POST /_clock/set_current_utc` with pinned startup default `2026-08-01T00:00:00Z`; rollover ops run applies carryover decay (0.99^n beyond 6-month grace) and term-expired contract completion.
- All formula-derived asserts were pre-computed and verified as literals (moisture 14.3/8.7/10.0, blends 13.38/12.75, prices 555/530/500/440/100, settlements 390080/368000/323840/73600/460000, pro-rata 750/2250 + tie-break 501/500, decay 12.00→11.3, indemnity 0 vs 1200000).

## Step 3: Copy Shared Files — 2026-08-15T01:50:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1929_hop_farm_contract_supply/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T02:05:00.000Z

All checks pass. The one "missing" constant `0.08` is the intended prose rendering "8 percent processing loss" (the skill's unit-conversion guidance), with the 0.92 multiplier conveyed through the worked 104+104 → 191 contrast. The PRD is complete and shipped.

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1929_hop_farm_contract_supply/workspace/PRD.md` — 306 lines.

**Section list:** §1 Introduction (3 paragraphs, business-context angle) · §2 Global Specifications (2.1 RBAC · 2.2 Response Structure verbatim · 2.3 Pagination · 2.4 Common Resource Properties & Version Counter · 2.5 Logical Clock & Crop-Year Boundaries · 2.6 OCC · 2.7 Units/Precision/Rounding · 2.8 Validation Priority Order · 2.9 Path Identifier Validation) · §3 Business Logic (3.1 Fields/Kilns/PlantingPlan · 3.2 Kiln Pipeline · 3.3 Lab Tests & Regrade Cascade · 3.4 Pelletizing & Cold Storage · 3.5 Contracts & Alpha Pricing · 3.6 Allocation Runs/Waterfall/Settlement · 3.7 Samples & Spot Market · 3.8 Insurance · 3.9 Rollover) · §4 Endpoint Definitions (56 rows) · §5 Error Catalogue (24 rows).

**Hard-contract results:**
- **Contract 1 (field names): PASS** — 82 required identifiers (60 entity fields, 42 endpoint inputs, 10 path params, plus common fields and composite-output keys): 75 present as standalone backticked tokens; the 7 remaining are path params (`plan_id`, `lot_id`, `test_id`, `allocation_id`, `sale_id`, `sample_id`, `claim_id`) appearing verbatim inside backticked §4 path tokens, matching the example-prd.md precedent. Verified mechanically against parsed scaffold YAML.
- **Contract 2 (rules): PASS** — 13/13 validation tiers expressed as an explicit priority list in §2.8 with masking semantics; 1/1 OCC rule (amendments + `expected_contract_version` + `ERR_STALE_VERSION`/412, no race framing); 31/31 state transitions across 9 machines with preconditions and side effects; 9/9 calculations in reconstructible prose (variety yield table, 0.24 bone-dry floor + feasibility envelope, aggregate-then-round pellet blend with the 104+104→191-vs-192 worked contrast, alpha gap pricing with 100-cent clamp and exact-floor boundary, pro-rata floor-plus-remainder waterfall with tie-breaks and both invariants, supersede, dual indemnity variants, 6-month-grace/1-percent compounding carryover decay, half-open 30-minute kiln buffer with exact-adjacency allowance); 24/24 errors mentioned in §2/§3 near their workflows; all 56 endpoints' side effects traced.
- **Contract 3 (§3 path purity): PASS** — 424 backticked tokens scanned, zero paths/methods/method+path combos.
- §2.2 emitted byte-identical to `section-2.2-response-structure.md`; §4 table is 4-column minimal; §5 is 2-column, status-only.

**Coverage audit (scaffold → PRD trace):** all 11 entities (incl. `LabTest` as the `common_fields: false` exception — only `id`/`created_at`, stated twice), 9 state machines, 9 calculations, 13 validations, 56 endpoints, 24 errors, 4 opaque roles (each named in §2.1 identity prose, with `filed_by_user_id` called out as the sole persisted/compared identifier), 1 concurrency rule, all enums (varieties, test types, outcomes, both pellet-lot state dimensions) — all traced to prose.

**Deliberate interpretations/compressions (flagged for the record):**
1. **Lab-test DRIED gate**: scaffold endpoint text says "lot must be DRIED," but FINAL-after-pelletize regrade and settle-finality would be unreachable under a strict reading (sources are `CONSUMED` by then; the HarvestLot machine explicitly keeps alpha fields "for downstream regrade"). PRD renders the gate as `DRIED` or `CONSUMED` accepted, kiln-pipeline states rejected with `ERR_LOT_NOT_DRIED`.
2. **Spot-draft on non-`AVAILABLE` lot** → `ERR_INVALID_STATE` (implied by the `AVAILABLE → RESERVED` transition; no dedicated catalog error exists).
3. **Constants as prose**: `PROCESSING_LOSS_PCT 0.08` rendered as "8 percent processing loss" with 0.92 implicit via the worked example; `INITIAL_WATER_FRACTION 0.76` rendered as the physical justification ("green hops carry 76 percent water") since the formula operates on the 0.24 bone-dry floor.
4. **Suspend/settle interaction left unspecified** — scaffold's suspend side effect names only confirm/deliver as blocked; PRD states exactly that and does not speculate about settling a suspended contract's allocation.
5. **Undefined pelletize case** (a source lot with neither provisional nor final alpha) is undefined in the scaffold; PRD stays silent rather than inventing a rule.

## Step 5: Generate Unit Tests — 2026-08-15T02:30:00.000Z

Generation complete for task_1929_hop_farm_contract_supply. Summary:

## Files written

**`test_helpers/`** (Stage 1) — all under `/home/ubuntu/github/CodingPRD/tasks/task_1929_hop_farm_contract_supply/test_helpers/`:
- `types.py` — 11 status/type enums + 11 entity TypedDicts; `LabTest` correctly omits `updated_at`/`version` (append-only per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with 40 endpoint methods covering every PRD §4 endpoint plus `/_clock/set_current_utc`
- `api_errors.py` — all 24 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions (LabTest asserts *absence* of version/updated_at) + `assert_allocation_volume_invariants`
- `factories.py`, `constants.py` (base-yield table, 0.24 bone-dry floor, 10.0% moisture gate, 30-min buffer, 8% processing loss, 100-cent price floor, 0.75 default coverage, 6-month grace / 1% decay, startup clock, pre-spaced kiln windows), `test_users.py`, `fixtures.py`, `__init__.py`

**`test_suite/`** (Stage 2): `conftest.py` + 11 test files (`test_01` envelope/auth/RBAC … `test_11` insurance claims), **78 tests total**, all collected cleanly.

## Test counts per source

- **Queue A (Difficulty): 36 tests** — all 18/18 instances at exactly 2 tests each
- **Queue B (Corner): 42 tests** — 42 of 43 non-stub instances at 1 test each
- All 9 `excluded_because:` stubs verified to resolve to real difficulty instances; none translated
- Tag audit: 78/78 tests carry exactly one `Design:` line at docstring end, all resolving to real instances (60 unique tags); 98 quoted PRD spans verified verbatim against PRD.md (whitespace-normalized); zero skip/xfail markers; zero scaffold leakage in comments

## Instances skipped (1)

- `Corner/entities/field_create_system_id_input_ignored` — fails **unique derivability** (condition 2). The instance asserts a client-supplied `id` is silently ignored and the server mints its own. But PRD §2.8 tier 4 states "unknown body fields rejected — any failure yields `ERR_INVALID_REQUEST`", and §4 declares only `name`/`acreage` as create inputs. A faithful PRD-only reader could legitimately return 400 instead of 201-ignored, so the asserted outcome is not uniquely derived. (Sibling tasks with identical "unknown body fields rejected" language likewise omit this test.)

## Notable fixture/factory decisions

- **All four roles are opaque** (PRD §2.1): no entity-backed header threading. Segregation-of-duties flows use explicit-id builders — `make_farm_manager_headers("grower-1")` files, `make_insurance_adjuster_headers("adjuster-9")` reviews/decides/pays; same-id variants drive the `ERR_SEGREGATION_OF_DUTIES` test.
- `fixtures.py` tiers: farm hierarchy (`setup_harvesting_plan_with_kiln`), kiln pipeline lifecycle (`create_dried_lot` walks load→finish→release and auto-posts a matching PROVISIONAL whenever a FINAL is requested, satisfying the PRD §3.3 gate), allocation composites (`setup_delivered_allocation` / `setup_settled_allocation` with per-source alpha/window control), `setup_two_consecutive_shortfall_years` for the default cascade, and claim helpers (`file_claim_on_growing_plan`, `drive_claim_to_approved`).
- All (wet, dried) pairs were pre-checked against the feasibility envelope and 10.0% release gate so fixtures never trip `ERR_WEIGHT_IMPOSSIBLE`/`ERR_MOISTURE_UNSAFE` incidentally.
- Version assertions (`== 1` at create, `+1` per mutation) cite PRD §2.4 "starts at its initial value" following the established benchmark precedent for that exact phrasing (tasks 0994, 1241).
- Every expected literal (555→530 repricing, 191 vs 192 rounding order, 501/500 tiebreak, 460000/1200000 settlements, 11.30 carryover decay, etc.) was recomputed from the PRD formulas and matches the design-index pre-computed values.

## Step 6: Generate Implementation — 2026-08-15T02:30:00.000Z

The implementation is complete and verified. Final summary:

## Files written (23)

All under `/home/ubuntu/github/CodingPRD/tasks/task_1929_hop_farm_contract_supply/workspace/implementation/`:

- `start.sh` (executable, guarded `pip install`, `exec python3 app.py`, `PORT` env default 10000, binds 0.0.0.0) + `requirements.txt` (flask)
- `app.py` — Flask entry, error handlers, global request lock, blueprint registration
- `db.py` — in-memory store (11 dicts keyed by UUID) + logical clock (default exactly `2026-08-01T00:00:00Z`, never falls back to wall clock)
- `errors.py` — all 24 catalog error IDs with exact HTTP statuses; `response.py` — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination `limit`/`offset`/`total_count`/`has_more` in meta, defaults 10/0, min 1 max 100); `middleware.py` — `X-User-ID`/`X-User-Role` auth with the four opaque roles; `util.py` — strict request-shape validation (unknown fields rejected, bool-rejection for ints, exact Decimal range checks)
- `services/core.py` — record factory (`version` starts 1, `touch()` per mutation event), all calculations, cascades, list filtering
- `routes/` — 12 modules: fields, kilns, planting_plans, contracts, harvest_lots, lab_tests, pellet_lots, allocations, spot_sales, samples, insurance_claims, ops (rollover + `/_clock/set_current_utc` outside `/api`)

## Endpoint count: 56

All from PRD §4: fields 2, kilns 2, planting-plans 8, contracts 7 (incl. OCC-guarded amendments), harvest-lots 7, lab-tests 3, pellet-lots 3, allocation-runs 1 + allocations 6, spot-sales 5, samples 4, insurance-claims 6, rollover 1, clock 1.

## State machines: 10

PlantingPlan (with revise/cancel lot-existence gates and pipeline-empty completion), Contract (suspend/reinstate loop, terminate cascade, system default at counter 2, system completion at rollover), HarvestLot (kiln redry loop with moisture gates), PelletLot `inventory_status` + independent `age_class` (parallel dimensions), Allocation (confirm FIFO / deliver / settle / cancel + supersede), SpotSale, BrewerySample (pair-level resend loop), InsuranceClaim (SoD on review/decide/pay). Every cascade touch increments each affected resource's `version` and refreshes `updated_at`.

## Calculations: 9

projected_yield, kiln_moisture (exact integer form `(100·dried − 24·wet)/dried`, 1dp half-up), pellet_blend (pinned aggregate-then-round; worked example 104+104→191 verified), alpha_price_adjustment (premium/discount with 100-cent floor clamp, single final rounding), pro_rata_allocation (exact `Fraction` floor shares + largest-remainder distribution, ties by contract `created_at`), allocation_run_supersede, indemnity_payment (preliminary at filing vs final at pay), carryover_decay (full calendar months, 6-month grace, 0.99^n compounding, fires once), kiln_window_conflict (half-open intervals, 30-min buffer, exact adjacency allowed on both sides).

## Storage design

Pure in-memory dicts, empty at every boot (no seeding); a global RLock serializes all requests so multi-resource cascades are atomic; logical clock stamps `created_at`/`updated_at`/`entered_storage_at` and drives months/rollover math; an internal `_seq` counter (stripped from output) deterministically breaks ties among identical logical timestamps for sort and FIFO order.

## Verification

~150 live checks across 4 smoke suites, including boots via `bash start.sh` and kill/relaunch cycles simulating `--isolation per-test-server`: boot-to-HTTP ~28 ms, store empty and clock reset after every restart, all error IDs/statuses spot-checked, regrade cascade numbers traced (12.7549→12.75, price 513→515), default cascade releasing CONFIRMED reservations, terminate-vs-completion asymmetry for DELIVERED allocations, no-double-decay on repeated rollovers.

## PRD interpretations to reconcile in Step 8

1. **Posted `alpha_pct` rounded half-up to 2dp at post time** — PRD §2.7 lists "a posted `alpha_pct`" among 2dp alpha values, so the LabTest stores the rounded value (12.505 → 12.51). `alpha_floor_pct`/`coverage_pct` preserve supplied precision (explicit in §2.7).
2. **Body-referenced FK ids → 404** — priority 3 covers only path ids; I return `ERR_NOT_FOUND` for missing body FKs (`field_id`, `planting_plan_id`, `harvest_lot_id`, `kiln_id`, `pellet_lot_id`, `source_lot_ids` entries), checked after request-shape validation.
3. **Pelletize with untested source lots** — `blended_alpha_pct` = null when no source lot has any alpha; with partial data, the blend weights only tested lots (numerator and denominator both exclude untested). No error ID exists for this case, so I don't reject. Downstream, `delivered_alpha_pct`/`estimated_unit_price_cents` are null if a delivered lot's blend is null (unreachable at settle given the all-finals precondition).
4. **Duplicate ids in `source_lot_ids` → 400** (defensive; spec silent).
5. **`reserved_lot_ids` retained after deliver** (equal to `delivered_lot_ids`); cleared only when a CONFIRMED allocation is cancelled, per the side-effect text.
6. **Settle-induced auto-default counts as one contract mutation** (counter + status change together = version +1), per §2.4's per-resource-per-call increment rule.
7. **Deliver is gated on contract ACTIVE** in addition to confirm (PRD §3.5 names both; scaffold validations table names only confirm — PRD wins). Settle/cancel are not gated.
8. **`created_allocation_ids` order** = contract `created_at` ASC (unspecified in PRD; deterministic).
9. **Clock may be set to any well-formed instant**, forward or backward (PRD says "advance" but defines no regression error).
10. **`created_at`/`updated_at`/`api_request_timestamp` come from the logical clock** (§2.5: all temporal evaluation reads the logical clock); list ties resolve by insertion sequence.
11. **405/unknown paths → `ERR_NOT_FOUND` 404 envelope**; empty-string `name` accepted (no non-empty constraint specified).

## Step 7: Run Tests and Iterate — 2026-08-15T03:00:00.000Z

Clean 8-round parallel sweep achieved: 78/78 passed in every round.

## Summary

**Iterations run: 2**

**Iteration 1 failures (union across 8 rounds, both deterministic 8/8):**
1. `test_03_kiln_pipeline_and_moisture.py::TestRedryLoop::test_redry_returns_lot_to_kiln` — assertion compared the echoed `kiln_window_start` byte-exactly (`"…12:30:00Z"` vs implementation's canonical `"…12:30:00.000Z"`).
2. `test_07_allocation_runs_prorata.py::TestRemainderTiebreak::test_equal_fractions_tiebreak_by_earlier_created` — `requests.exceptions.ConnectionError` mid-test under 8-way parallel load.

**Tests deleted: none.**

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1929_hop_farm_contract_supply/test_suite/test_03_kiln_pipeline_and_moisture.py` — `test_redry_returns_lot_to_kiln` now compares `kiln_window_start` as a parsed instant instead of a raw string. PRD §3.2 covers the rule verbatim ("redrying … updates the recorded window on the lot"), but is silent on the echo *format* of request-supplied datetimes (§2.4's three-fractional-digit rule names only server-generated `created_at`/`updated_at`). Byte-equality was not uniquely derivable (a faithful implementer may canonicalize); instant-equality is. STEP 1c partial-coverage handling: kept the covered assertion, dropped the non-derivable formatting requirement. No assertion weakened — the window value itself is still verified.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1929_hop_farm_contract_supply/test_helpers/api_client.py` — set `Connection: close` on the shared session. The tiebreak failure was a transport-layer flake: the session-scoped `requests.Session` pooled keep-alive connections that go stale when the harness SIGKILLs and respawns the server before every test (per-test-server isolation); under 8 concurrent rounds the stale socket raced the restart and got RST mid-test. Diagnosis confirmed the implementation was not at fault: a manual replay of the exact request sequence and a solo (non-parallel) round both produced the correct 501/500 tiebreak allocations. Fresh TCP per request matches the isolation model; no assertion or precondition changed.

**Fixes applied to `implementation/`: none** — the implementation was correct on both counts.

**Verification:** final sweep — rounds 1–8 each `78/78 passed, 0 failed, 0 errors` under full 8-way parallelism.

## Step 8: Finalize PRD — 2026-08-15T03:15:00.000Z

Done. The diff is exactly one inserted sentence at §2.4; everything else is verbatim.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1929_hop_farm_contract_supply/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 306 lines → PRD_FINALIZED.md 306 lines, 0.0% delta (single sentence inserted inline within an existing paragraph; diff confirms only line 78 changed).

**Changes (one total):**
- §2.4 (Common Resource Properties and the Version Counter) — insert — appended one sentence pinning that request-supplied datetime values (`kiln_window_start`/`kiln_window_end` on kiln load/redry, and the clock's `to_iso8601`) are stored as instants and echoed in the canonical ISO 8601 UTC three-fractional-digit form (`…12:30:00Z` reads back as `…12:30:00.000Z`) — `implementation/services/core.py:81-91` (`public()` renders every datetime via `fmt_ts`), `implementation/db.py:46-53` (`fmt_ts`), `implementation/util.py:107-114` + `db.py:33-43` (`req_datetime`/`parse_iso`), `implementation/routes/harvest_lots.py:93-94,105-106,139-140,153-154`, `implementation/routes/ops.py:31-33`.

**Step 7 item disposition:**
- Item 1 (`test_redry_returns_lot_to_kiln` byte-exact echo) → PRD silence, patched by the edit above.
- Item 2 (`test_equal_fractions_tiebreak_by_earlier_created` ConnectionError) → pure test_helpers transport flake (`Connection: close`); implementation verified correct and PRD §3.6 already pins the tiebreak verbatim ("ties broken in favor of the contract created earlier"). No edit.

**Per-edit pre-edit search log (edit 1 of 1):**
- (a) Subject: storage/echo format of request-supplied datetime values.
- (b) Impl paths enumerated and read/grepped: all `req_datetime` callsites (harvest_lots.py:93-94 load-kiln, 139-140 redry; ops.py:31 `to_iso8601` — confirmed exhaustive via grep); the parse path (`util.py:107-114` → `db.py:33-43`); every datetime-emission site (`response.py:19` `api_request_timestamp`; `core.py:56,70,77` `created_at`/`updated_at`; `core.py:88` `public()` covering lot windows on POST echoes and GET/list; `ops.py:33` `current_utc`; `pellet_lots.py:56` `entered_storage_at`); global grep for `strftime`/`isoformat`/`fmt_ts` confirmed `fmt_ts` is the only rendering path. All emit exactly three fractional digits, so the wording is true on every path.
- (c) Wording adjustment: scoped the sentence to request-supplied fields only (explicitly not claiming anything new about server-stamped fields like `entered_storage_at`, which §3.4 already covers as clock-stamped), and pinned only the *rendering form* — not input-syntax acceptance or offset normalization — since Step 7 exercised only the `Z`-form fractional-digit echo; untested input variants remain deliberately under-determined.

## Step 9: Complete PRD — 2026-08-15T03:35:00.000Z

All changes are in place and self-consistent. PRD_COMPLETED.md is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1929_hop_farm_contract_supply/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 306 lines / 48,430 chars → `PRD_COMPLETED.md` 306 lines / 51,505 chars. Char delta: **+3,075** (16 diff hunks, all in-paragraph inserts/revisions; no new sections, no deletions of behavior).

**Counts:** 4 mismatch-revisions, 17 ambiguity-pins.

### Mismatch-revisions

- **§2.6** — revise — mismatch — OCC guard fires on any inequality of `expected_contract_version`, not only when the current version "has advanced beyond" the observed one; missing/non-integer value is `ERR_INVALID_REQUEST` — `implementation/routes/contracts.py:117-120,133-134`
- **§2.8** — revise — mismatch — swapped tiers 3/4: request-shape validation precedes resource-existence validation on every endpoint (all action handlers validate body before resolving the path id) — `implementation/routes/harvest_lots.py:90-99`, `implementation/routes/allocations.py:75-76`, `implementation/routes/samples.py:70-74`, `implementation/routes/insurance_claims.py:95-97`, `implementation/routes/contracts.py:116-129`
- **§2.9** — revise — mismatch — existence checking follows request-shape validation (a malformed body on an unknown id yields 400, not 404) while still preceding all business-rule checks — same impl evidence as above
- **§3.6** — revise — mismatch — auto-default fires whenever the counter stands at ≥2 after a settlement update with the contract ACTIVE (not only at the moment it "reaches 2"); a SUSPENDED contract crossing the threshold defaults at a later settlement once reinstated — `implementation/routes/allocations.py:161-168`

### Ambiguity-pins

- **§2.2** — insert — ambiguity — `api_request_timestamp` is stamped from the logical clock — `implementation/response.py:19` (`store.now_str()`)
- **§2.3** — insert — ambiguity — non-integer/out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST` — `implementation/response.py:66-88`
- **§2.3** — insert — ambiguity — `created_at` sort ties break by creation (insertion) order — `implementation/services/core.py:94-97` (`_seq`)
- **§2.3** — insert — ambiguity — `has_more` = `offset + len(page) < total_count` — `implementation/response.py:39`
- **§2.3** — insert — ambiguity — malformed filter values → `ERR_INVALID_REQUEST`; unrecognized query params ignored — `implementation/services/core.py:559-591`
- **§2.4** — insert — ambiguity — `version` starts at 1; `updated_at` initialized equal to `created_at`; both stamped from the logical clock — `implementation/services/core.py:53-63`
- **§2.8 (item 3)** — insert — ambiguity — malformed/non-object JSON body is a shape failure; `source_lot_ids` entries must be distinct; string fields carry no non-emptiness/length/format/uniqueness constraint — `implementation/util.py:12-23,126-127,33-37`
- **§2.8 (item 4)** — insert — ambiguity — body-carried identifiers (`field_id`, `planting_plan_id`, `kiln_id`, `harvest_lot_id`, each `source_lot_ids` entry in array order, `pellet_lot_id`) are existence-checked after the path id, surfacing `ERR_NOT_FOUND` — `implementation/routes/planting_plans.py:35`, `harvest_lots.py:44,99`, `lab_tests.py:27`, `pellet_lots.py:28-33`, `samples.py:28`, `spot_sales.py:33`, `insurance_claims.py:43`
- **§2.9** — insert — ambiguity — unmatched path or unsupported method on a matched route yields `ERR_NOT_FOUND` (405→404 mapping) — `implementation/app.py:31-38`
- **§3.2** — insert — ambiguity — redry keeps the lot on its already-recorded kiln; the request carries only the fresh window — `implementation/routes/harvest_lots.py:138,151`
- **§3.4** — insert — ambiguity — blend skips alpha-less source lots in both numerator and denominator, is null when no source has alpha; a provisional posted after pelletizing does not move the blend — `implementation/services/core.py:244-264`, `implementation/routes/lab_tests.py:58-65`
- **§3.5** — insert — ambiguity — alpha price adjustment reads the contract's current terms at computation time (delivery for estimate, settlement for final); amendments never recompute staged estimate fields — `implementation/routes/allocations.py:123,153`, `implementation/routes/contracts.py:136-139`
- **§3.6** — insert — ambiguity — `ERR_EMPTY_DELIVERY` gate is evaluated after the from-state and contract-active gates — `implementation/routes/allocations.py:105-112`
- **§3.6** — insert — ambiguity — null `blended_alpha_pct` on any delivered lot → `delivered_alpha_pct` and `estimated_unit_price_cents` stay null until the regrade cascade — `implementation/services/core.py:267-280`, `implementation/routes/allocations.py:121-126`
- **§3.6** — insert — ambiguity — FIFO reservation order has a final tiebreak by creation order after `entered_storage_at`/`created_at` — `implementation/services/core.py:469`
- **§3.7** — insert — ambiguity — sample resends allowed whatever the prior outcomes, selection included (only lot inventory state gates sampling) — `implementation/routes/samples.py:30-41`
- **§3.8** — insert — ambiguity — `indemnity_final_cents` is null on the claim until payment — `implementation/routes/insurance_claims.py:66`
- **§3.9** — insert — ambiguity — storage months counted anniversary-style by day-of-month, floored at zero; null blend flips to CARRYOVER with no decay; returned id lists ordered oldest-first — `implementation/services/core.py:503-508,526-532,517,537`

**Notable verified matches requiring no change:** all 24 error ids and HTTP statuses (§5 vs `errors.py` and every raise site), all endpoint paths/roles (§4 vs every route), the kiln 30-minute half-open buffer rule, the moisture envelope and formula, aggregate-then-round pelletizing with the 191-vs-192 contrast, the largest-remainder pro-rata waterfall with early-created tiebreak, regrade cascade scope (DELIVERED only, SETTLED never reopened), termination/default/completion cascade asymmetries, SoD before state (tier 5 < 6, `insurance_claims.py:97-99`), and field-season conflict before acreage ceiling (tier 8 < 12, `planting_plans.py:37-47`).
