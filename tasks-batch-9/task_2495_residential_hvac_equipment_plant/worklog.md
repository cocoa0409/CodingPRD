# Worklog — task_2495_residential_hvac_equipment_plant

## Step 1: Create task directory — 2026-09-03T01:15:16.646Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2495_residential_hvac_equipment_plant` and `.../workspace`. Index 2495 was pre-assigned by the invoking pipeline (no auto-allocation scan performed, per orchestrator instructions — up to 32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T02:36:43.620Z

All three scaffold artifacts are complete and pass `scaffold_lint.py` with `VERDICT: clean lint`.

**Generated at `/home/ubuntu/github/CodingPRD/tasks/task_2495_residential_hvac_equipment_plant/`**

- `SCAFFOLD.yaml` (§1.0–§1.7, 157 KB): 15 entities, 12 state machines with 59 transitions, 11 calculations (leak verdict, run-test performance verdict, allocation fill plan, supply effective capacity, warehouse pallet occupancy, pre-season carrying cost, warranty claim rate, warranty posture, supply derate plan, regional salability, test-cell window eligibility), 38 validation rules across 10 priority bands (10–100), 3 priority-pair conflicts, 2 concurrency (OCC) rules, 74 endpoints, 45 errors, 11 roles. Profile: `role_model: segregation_of_duties`, `consistency_model: immediate`, logical clock via `POST /_clock/set_current_utc` (default 2026-08-01T00:00:00Z).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8): all 9 §0.5 rule_ids × 2 differentiated instances = 18 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9): 48 instances across all 9 guide sections — entities 9, state_machines 8, calculations 5, validations 8, endpoints 4, errors 4, rbac 3, cross_cutting_complexity_layers 6, consistency_model 1 — of which 44 carry full `test_recipe` chains and 4 are `excluded_because` stubs citing the §1.8 instances that already cover them.

Verification performed beyond the linter: all `grounds:` entries resolve to declared §1.1–§1.7 elements in both design files; every `${var}` is bound by an earlier `captures:` in the same instance; all instance names unique across both files; every `excluded_because.difficulty_instance` exists in the difficulty design; every `claim_type` is a snake_case row from `references/claim-extraction-guide.md`; no forbidden concurrency vocabulary anywhere. Total calls scanned by the linter across §1.8+§1.9: 655.

Two issues fixed during finalization worth noting: a flow-style capture `{ capa_id: $.data[0].id }` broke YAML parsing until quoted, and `complexity_profile.logical_clock` / `state_machines.RefrigerantProgram.CREATE_to_ACTIVE` were dangling grounds references (the scaffold has no such profile key and no such transition) that the linter does not check — it validates calls and FK reachability only, not `grounds`.

## Step 3: Copy shared files — 2026-09-03T02:36:55.607Z

Copied `./INSTRUCTION.md` → `tasks/task_2495_residential_hvac_equipment_plant/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T02:52:00.000Z

Orchestrator truncation check (per known doc-generator failure mode): PRD.md is 471 lines and ends at `| `ERR_SHIP_UNITS_EXCEED_ALLOCATION` | 422 |` — a complete final row of the §5 error table, a real section boundary. Six top-level sections present (§1 Introduction … §5 Error Code Catalogue). NOT truncated; no regeneration needed.

Subagent summary (verbatim):

PRD generation for `task_2495_residential_hvac_equipment_plant` is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2495_residential_hvac_equipment_plant/workspace/PRD.md` — 472 lines, ends cleanly at the final row of the §5 error table (no truncation, no audit footer, no `<!--APPEND-->` sentinel left behind).

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim block); 2.3 Pagination; 2.4 The Logical Plant Clock; 2.5 Record Identity, Audit Fields, and Versioning; 2.6 Measurement Precision and Rounding; 2.7 Sub-Resource Reads and Path Resolution; 2.8 Stale-Version Guards on Certification Filing and Component Allocation; 2.9 Cascade Discipline and Derived-Field Reconciliation; 2.10 Segregation of Duties; 2.11 Order of Rule Evaluation
- §3 Business Logic & Workflows — 3.1 The Refrigerant Transition Calendar; 3.2 Publishing Regional Efficiency Standards; 3.3 The Platform Design Record: Draft, Review, Release, Retire; 3.4 Efficiency-Rating Certification and Regional Salability; 3.5 Constrained Components and the Allocation of Kits; 3.6 Staging, Shipping, and Cancelling Distributor Demand; 3.7 Seasonal Levelling: Warehouses and Pre-Season Pallet Space; 3.8 Building a Lot: Coil Fabrication, Leak Test, Charge, and Run Test; 3.9 Warranty Feedback: Claim Rate, Design Posture, and Supplier Corrective Action
- §4 Endpoint Definitions (4-column table, 74 rows)
- §5 Error Code Catalogue (2-column table, 45 rows)

**Coverage counts (all mechanically verified against SCAFFOLD.yaml)**
- 15/15 entities, 151/151 entity fields
- 12/12 state machines, 59/59 transitions (all states narrated; the 11 flagged "missing" endpoints were the `CREATE` pseudo-state and the `RECORDED` append-only pseudo-state of LeakTest/RunTest, which have no stored `status` field)
- 11/11 calculations, 37/37 validations, 3/3 priority-pair conflicts, 2/2 concurrency rules
- 74/74 endpoints, 45/45 errors, 11/11 roles
- 0/0 missing enum values (every enum literal of every field appears in §1–§3 prose)

**Hard Contract 1 — Field-Name Coverage: PASS.** 147 unique required identifiers (120 entity field names + 100 endpoint request-body/query/path identifiers, deduplicated). 1718 backticked spans in the document; 0 missing.

**Hard Contract 2 — Rule Coverage: PASS.** All 45 error IDs appear in §1–§3 (not only in the §5 table); all 37 validation errors, all 59 transition triggers/preconditions/side-effects, all 11 calculations including both dual-variant selectors (`platform_warranty_claim_rate` BUILT_BASIS/SHIPPED_BASIS, `preseason_carrying_cost` PER_RESERVATION/POOLED, `allocation_fill_plan` PRO_RATA/PRIORITY_FIRST), both non-separable 2-D tables reproduced cell-by-cell with an explicit non-separability note, the 10-band priority ladder plus all 3 priority-pair conflicts, both OCC guards, the 4-hop warranty cascade, and both sibling branches of the corrective-action closure (`CLOSED_EFFECTIVE`/`CLOSED_INEFFECTIVE`) and the certification decision at matched density.

**Hard Contract 3 — §3 Path Purity: PASS.** 0 violations across §3's 185 lines: no backticked token starts with `/`, is a bare HTTP method, or combines method+path; 0 plaintext occurrences of `/plant` in §3. Endpoints in §3 are named only by transition pair, role+action verb, or capability description.

**Two scaffold inconsistencies resolved by judgement (worth noting for the impl/test steps):**
1. Reservation build-eligibility: the `WarehouseReservation` CREATE precondition forbids only `{RELEASED_TO_STOCK, SCRAPPED, CANCELLED, HOLD_REGULATORY}`, while `validations.reservation-build-eligibility` and the `ERR_RESERVATION_NOT_ALLOWED_FOR_BUILD` condition also forbid `{LEAK_PASSED, CHARGED, RUN_PASSED}`. The PRD adopts the two-source majority reading: space may be booked only at `DRAFT`, `COIL_FAB`, `BRAZED`, or `REWORK`.
2. `validations.role-authorization` says "X-Role header"; the PRD uses `X-User-Role` per the skill mandate, with `ERR_UNAUTHORIZED` (403) covering absent, unrecognized, and not-permitted since no separate missing-header error exists.

Also filled two scaffold silences: `version` starts at 1 and increments by exactly 1 per mutation; the `applied_efficiency_tolerance` 0.90 floor is stated and noted as never binding for the table's values.

## Step 6: Generate implementation — 2026-09-03T03:26:00.000Z

(Steps 5 and 6 were launched concurrently as background subagents; Step 6 returned first. `test_suite/` did not exist when Step 6 started, giving the impl generator physical isolation from the tests.)

Subagent summary (verbatim):

Implementation complete, verified, and smoke server terminated (port 18495 free, no stray `app.py` processes, `__pycache__` removed).

**Files written** — all in `/home/ubuntu/github/CodingPRD/tasks/task_2495_residential_hvac_equipment_plant/workspace/implementation/`:

`start.sh`, `requirements.txt` (`flask>=2.0`), `app.py`, `db.py`, `web.py`, `errors.py`, `validate.py`, `prec.py`, `derive.py`, `calc.py`, `cascade.py`, `find.py`, `routes_design.py`, `routes_supply.py`, `routes_ops.py`. No other files or subdirectories.

**Module layout**

- `start.sh` — `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded `pip install -q -r requirements.txt` only if `import flask` fails, then `exec python3 app.py` in the foreground; binds `0.0.0.0` on `$PORT` (default 10000).
- `app.py` — `create_app()` registers three blueprints with `strict_slashes = False`; handlers for `ApiError`, 404 → `ERR_NOT_FOUND`, 405 → `ERR_METHOD_NOT_ALLOWED`, and a catch-all. `threaded=True`, no reloader, no debug.
- `db.py` — one `Store` of 15 in-memory dicts behind an `RLock`, insertion-ordered with a monotonic `_seq` for deterministic ASC/DESC cascade ordering; logical clock defaults to `2026-08-01T00:00:00Z`. Nothing seeded, ever.
- `web.py` — role table (11 roles), request-id/meta/envelope construction, the `@endpoint(roles, status)` decorator (lock → role gate first → envelope → `ApiError` translation), JSON body parsing with `Decimal` floats, pagination (`limit` default 10, 1..100), query filters.
- `validate.py` / `prec.py` — field validators returning both echoed and parsed forms; `Decimal`/`Fraction` helpers with ROUND_HALF_UP and integer-floor truncation.
- `derive.py` — every `source: computed` field recomputed at read/use time plus a `serialize_*` per entity, so the conserved identities hold by construction.
- `calc.py` — leak/run-test verdicts and tolerance tables, eligible-pool selection, `allocation_plan` for both policies, occupancy/carrying-cost math, derate bands.
- `cascade.py` — reusable multi-hop cascades (supply rebalance, order allocation reconcile, platform restrict/retire, program sell-through/expire, build reservation release) with ASC into cascades and DESC for line revocations.
- `routes_*.py` — design/certification, supply/allocation/orders, and operations (warehousing, build line, testing, warranty/CAPA).

**Endpoint count**: 74 registered rules, matching PRD §4 exactly.

**Notable interpretation decisions**

- The §2.11 precedence ladder overrides per-section prose wherever they conflict, corroborated by the scaffold's numeric `validations[].priority`: payload shape (20) before FK resolution (30); duplicate cert (30) before stale platform version (40); stale supply (40) before order state (50) and region gate (70); order state (50) before `ERR_ORDER_NOT_OWNED` (60); build stage (50) and manufacture window (70) before charge limit (80); warranty posture before manufacture window on build creation (scaffold line order); SoD (60) before flammable prohibition (70); `ERR_PLATFORM_HAS_OPEN_BUILDS` and `ERR_SHIP_UNITS_EXCEED_ALLOCATION` last (100). Certification submit follows PRD prose order (cert state → platform RELEASED → standard not found → efficiency minimum).
- Computed fields are never stored; `version` bumps only at PRD-declared triggers, including recompute-as-mutation on platform, warehouse, supply, and program.
- Declared enum query params on computed reads (`basis`, `policy`) are strict (422 on unknown values); plain list-filter params are lenient (an unknown value simply matches nothing).
- `carrying-cost` requires `window_start`/`window_end` (missing → `ERR_INVALID_REQUEST`) but never raises `ERR_INVALID_INTERVAL`, which is scoped to reservation creation and run tests.
- `occupancy` reports `on_date` = the `on_date` param, else `window_start`, else the clock date; `peak_occupancy_units` is the max across the window days.
- `POST .../retire` accepts `reason` but stores nothing (no such field on ProductPlatform).
- Rows cache private parsed instants (`_manufacture_cutoff`, `_sell_through_deadline`, `_start_date`, `_window_start`, …); client-supplied date/datetime/month strings are echoed verbatim while system stamps come from the logical clock.

**Verification**: `bash start.sh` booted in the foreground on `PORT=18495`; `GET /plant/warehouses` returned the empty-array envelope with `limit/offset/total_count/has_more`, `GET /nope` returned `ERR_NOT_FOUND`, `DELETE /plant/warehouses` returned `ERR_METHOD_NOT_ALLOWED`. Three smoke scripts exercised: version accounting (platform 1→submit 2→return-to-draft→re-submit→release 5, cert decide), the depth-4 warranty→CAPA→derate→revoke→order-regression cascade (order regressed to UNALLOCATED while `fulfillment_status` stayed PENDING), CAPA EFFECTIVE restoring `available_units`, allocate/stage/ship with pool status reaching EXHAUSTED and `units_shipped_total` = 10, carrying cost under both bases, run-test tolerance ratios, the clock endpoint, sell-through (platform → RESTRICTED, build → HOLD_REGULATORY, reservation → RELEASED with `BUILD_ON_REGULATORY_HOLD`, warehouse `pallets_reserved_current` → 0), and expire (platform → RETIRED, cert → WITHDRAWN, build → CANCELLED, `affected_platform_count` → 0). Ladder errors observed as expected: 403 role, 422 shape/duplicate, 412 both stale guards, 409 SoD/order-state/capacity, 422 interval/hold-too-short/charge-limit, `ERR_MANUFACTURE_CUTOFF_NOT_REACHED`, `ERR_MANUFACTURE_WINDOW_CLOSED`, `ERR_SHIP_UNITS_EXCEED_ALLOCATION`.

`test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, and `SCAFFOLD_CORNER_DESIGN.yaml` were never read, listed, globbed, or grepped.

## Step 5: Generate unit tests — 2026-09-03T05:25:00.000Z

Subagent summary (verbatim):

Stage 1 and Stage 2 are complete for task 2495. Summary below is worklog-ready.

**Files written**

Infrastructure — `/home/ubuntu/github/CodingPRD/tasks/task_2495_residential_hvac_equipment_plant/test_helpers/`: `__init__.py`, `api_client.py`, `constants.py`, `factories.py`, `test_users.py` (16 users / 11 roles), `assertions.py`, `fixtures.py`, plus `test_suite/conftest.py` (session `api` fixture + one header fixture per user).

Test cases — `.../test_suite/` (13 files, 95 tests):
- Queue A (difficulty, 51 tests): `test_01_leak_verdicts_and_charging.py` 9, `test_02_run_tests_and_cell_scheduling.py` 6, `test_03_design_review_and_regional_gates.py` 8, `test_04_allocation_policy_and_conservation.py` 5, `test_05_warranty_derate_and_capa_cascade.py` 10, `test_06_warehouse_pallet_space.py` 8, `test_07_regulatory_cascade_and_preseason_release.py` 5.
- Queue B (corner, 44 tests): `test_08_registry_records.py` 9 (entities), `test_09_lifecycle_transitions.py` 8 (state_machines), `test_10_derived_values.py` 6 (calculations + consistency_model), `test_11_request_validation.py` 8 (validations), `test_12_reads_and_error_envelope.py` 7 (endpoints + errors), `test_13_authorization_and_versioning.py` 6 (rbac + cross_cutting).

**Coverage**

- Queue A: 18/18 instances covered, every instance carrying 2 to 4 tests (the >=2 rule holds everywhere).
- Queue B: 44/44 non-stub instances covered, exactly one test each.
- Instances skipped for PRD-first failure: **none** — all 62 non-stub instances passed both conditions.
- The 4 `excluded_because` corner stubs are intentionally untested (`c_allocation_preview_is_a_pure_read`, `c_sell_through_cascade_reaches_warehouse_capacity`, `c_leak_method_selects_the_pass_criterion`, `c_claim_rate_crossing_a_threshold_opens_a_capa`); all four cross-references were verified to resolve to difficulty instances that each own 3+ tests.

**Verification passes run mechanically over all 13 files**

- Every test docstring ends with exactly one `Design:` line, resolving to a real non-stub instance name (0 untagged, 0 dual-tagged, 0 dangling).
- Every docstring citation matches PRD.md verbatim modulo backtick/bold stripping and arrow written as "to"; one paraphrase found in `test_03` ("That region is blocked ... when this condition holds") was rewritten to the verbatim §3.4 sentence.
- Every asserted `error_id` appears in PRD prose, not only in the §5 table; every docstring has a >=8-word backtick-free greppable window; no `skip`/`skipif`/`xfail` anywhere; no "scaffold"/§1.x/"Table N" leakage in `test_helpers/` or `test_suite/`.
- Static resolution check: every name imported from `test_helpers`, every `api.<method>` call, and every fixture argument exists; no unused imports; all files compile.

**Known design-index deviations (deliberate, PRD wins)**

- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` line 1021 claims a 100-unit pool at `derate_pct == 25` yields `effective_allocatable_units == 25`; PRD §2.6/§3.5 defines the surviving-percentage formula, so tests assert 75 (and 75 for the 101-unit truncation case).
- Design indices assert bare-second timestamps while PRD §2.5 requires three fractional digits; all instant comparisons go through `assert_instant_equals` in `test_helpers/assertions.py`.
- Omitted as non-uniquely-derivable: the carrying-cost `basis`/`window_start`/`window_end` echo fields, and `rework_count == 3` on the scrap path.

**Constraint honored**: nothing under `workspace/implementation/` was read or written; the suite was authored blind to it, and the tests were never executed against it.

## Step 7: Run tests and iterate — 2026-09-03T04:53:12.863Z

Orchestrator note on timestamps: the Step 4/5/6 entry timestamps above were orchestrator estimates written without re-reading the clock and run ahead of the true host clock; the wall-clock times taken directly from `date -u` are Step 1 01:15:16Z, Step 2 02:36:43Z, Step 3 02:36:55Z, and this Step 7 entry 04:53:12Z. Step ordering is unaffected.

Orchestrator verification of the sweep artifacts (done independently of the subagent's claim, per known failure mode where a Step 7 agent reports a clean sweep with no results files on disk): all 8 of `workspace/implementation/results.{1..8}.json` exist, each parses, and each reports `passed == total == 95`, `failed == 0`. Their mtimes (04:42:30Z) postdate the `test_helpers/fixtures.py` fix (04:39:08Z), so this is genuinely the post-fix sweep and not a stale baseline. `workspace/sweep.log` ends with `Results: 95/95 passed, 0 failed, 0 errors, 0 skipped` and a normal port-registry release — no `Terminated`, so the setsid wrapper held and no round was reaped.

Subagent summary (verbatim):

Clean sweep verified — all 8 result files present on disk, each `passed == total == 95`.

## Summary

**Iterations run:** 2 (baseline sweep + one fix sweep).

**Tests deleted:** none. No test failed the STEP 1 PRD-coverage or unique-derivability checks.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — added a `read_program(program_id)` reader (GET `/plant/refrigerant-programs/{id}` as `PlantAdmin`, mirroring the existing `read_platform` / `read_warehouse` / `read_build_order` readers), and changed `setup_preseason_lot_with_reservation` to return `read_program(program["id"])` instead of the creation-time response body. The fixture was handing back a stale snapshot of the refrigerant program (version 1 as minted), so `test_07_regulatory_cascade_and_preseason_release.py::TestSellThroughCascade::test_entering_sell_through_restricts_the_released_platform` measured "version increases by one" against the wrong baseline.

**Fixes applied to `implementation/`:** none — no implementation defect was found.

**Key finding (the single failure, deterministic in all 8 baseline rounds):** `assert 3 == (1 + 1)` on the program version. The implementation was PRD-correct on both hops: PRD §3.3 states "The naming program's `affected_platform_count` is recomputed as part of the same write" for platform creation, and PRD §2.5 states "A recomputation of a derived field counts as a mutation ... The same holds ... for a refrigerant program whose `affected_platform_count` is recomputed" — so creating the platform legitimately took the program from version 1 to 2 (`routes_design.py:255`), and `enter_sell_through` (`cascade.py:224-229`) then bumped it exactly once more to 3. Per STEP 2 this was a test-side bug (fixture precondition snapshot), not grounds for weakening the implementation's PRD-required recompute-as-mutation behaviour. No flakiness was observed in either sweep: the failure was identical in all 8 baseline rounds and absent from all 8 post-fix rounds.

## Step 8: Finalize PRD — 2026-09-03T05:10:00.000Z

Step 8 ran (not skipped: Step 7 applied one `test_helpers/` fix, so the skip condition of zero deletions / zero test_suite fixes / zero test_helpers fixes / zero implementation fixes was not met). Orchestrator verified `workspace/PRD_FINALIZED.md` exists and is byte-identical to `workspace/PRD.md` (same md5), consistent with the subagent's zero-edit outcome.

Subagent summary (verbatim):

Created `/home/ubuntu/github/CodingPRD/tasks/task_2495_residential_hvac_equipment_plant/workspace/PRD_FINALIZED.md`.

## Outcome: zero edits (exact copy of PRD.md)

- PRD.md: 471 lines. PRD_FINALIZED.md: 471 lines. Delta: 0 lines, 0.00% (byte-identical, md5 `dc3b6944e0fd41ff9fe1e850a54b17f1`).
- Change list: none.

## Why zero edits

`<step_7_diff>` contains exactly one item: a `test_helpers/fixtures.py` fix (new `read_program()` reader; `setup_preseason_lot_with_reservation` now returns a freshly-read program instead of the creation-time body). No `implementation/` fix, no test deletion, no `test_suite/` change. The single failure (`assert 3 == (1 + 1)`) was a stale-precondition-snapshot bug on the test side, and I verified against `implementation/` that the behavior it mismeasured is already uniquely pinned by PRD.md, so there is nothing traceable to patch under the HARD SCOPE.

Verification performed (this doubles as the pre-edit search log for the one candidate edit I considered and rejected):

- **(a) Subject identified:** when and how often a refrigerant program's `version` changes — specifically the `affected_platform_count` recompute-as-mutation on platform creation, and the single bump on `enter-sell-through`.
- **(b) Impl paths enumerated:** grepped `affected_platform_count` (only `implementation/derive.py:24` computing it, `derive.py:46` serializing it, `routes_design.py:254` comment) and every `.touch(` callsite in `app.py`, `cascade.py`, `derive.py`, `routes_design.py`, `routes_ops.py`, `routes_supply.py`. Programs are touched in exactly three places: `routes_design.py:255` (platform creation), `cascade.py:227` (`enter_sell_through`), `cascade.py:235` (`expire_program`). Read `cascade.py` in full (`restrict_platform:176-181`, `retire_platform:184-211`, `enter_sell_through:224-229`, `expire_program:232-239`) plus `routes_design.py:204-315` (create/list/read/patch platform) and `derive.py:1-70`.
  - `affected_platform_count` is derived on read, never stored, so no other write needs a recompute event.
  - Platform creation bumps the program once -> version 1->2, exactly as PRD §3.3 ("recomputed as part of the same write") plus §2.5 ("a recomputation of a derived field counts as a mutation ... for a refrigerant program whose `affected_platform_count` is recomputed") require. `enter_sell_through` bumps once more -> 3, exactly as PRD §3.1 states; the RESTRICTED platforms it sweeps stay inside the counted state set, so no second program bump is implied.
  - Retirement (`cascade.retire_platform`) does change the count but performs no program touch — and PRD's four retirement hops (§3.3) and the expiry paragraph (§3.1) likewise mention no program recompute, so impl and PRD agree here too.
- **(c) Wording adjustment:** none — the only candidate edit was a §2.5 clarification scoping the program's recompute-driven bump to platform creation. Rejected as out of scope: Step 7 explicitly recorded no PRD-silence and no PRD-mismatch on this subject, the retirement path is not a `<step_7_diff>` site, and PRD.md already determines every version value the failing assertion touched.

Post-fix state is clean and non-flaky: 95/95 passed in all 8 rounds of the post-fix sweep (`workspace/sweep.log`).

## Step 9: Complete PRD — 2026-09-03T05:35:20.866Z

**Orchestrator decision — Step 9 was run as three sequential file-partitioned passes over a single shared `PRD_COMPLETED.md`, not as one subagent.** Reasoning: `implementation/` is 3615 lines across 13 modules, and a single-subagent exhaustive walk of that much code plus a 471-line PRD reliably degrades into a sampled walk whose tell-tale output is a `PRD_COMPLETED.md` byte-identical (or near-identical) to its source — i.e. a scan that never really ran. Partitioning by implementation file gives each pass a scope it can actually exhaust. Passes ran strictly sequentially (never concurrently) because all three edit the same output file; pass A created it from `PRD_FINALIZED.md`, passes B and C edited it in place and were told not to recreate it or re-litigate earlier passes' edits.

Partition used:
- Pass A — global / cross-cutting layer: `app.py`, `web.py`, `db.py`, `errors.py`, `validate.py`, `prec.py`, `find.py` (754 lines). Lands in §2 and §5.
- Pass B — design / certification / supply / allocation / orders: `routes_design.py`, `routes_supply.py`, `calc.py` (1227 lines). Lands in §3.1–§3.6.
- Pass C — plant operations / cascades / derived fields: `routes_ops.py`, `cascade.py`, `derive.py` (1634 lines). Lands in §3.7–§3.9, §2.9.

Aggregate result: **473 lines / 122,470 chars**, up from `PRD_FINALIZED.md`'s 471 lines / 106,120 chars — **+16,350 chars (+15.4%)** across **63 changes: 49 ambiguity-pins + 14 mismatch-revisions** (A: 15+2, B: 18+8, C: 16+4). Only two new lines in total; nearly every edit is an in-paragraph insert or revision, as the minimal-patch rule requires. No new sections.

Orchestrator verification of the final artifact (independent of the subagents' claims): `workspace/PRD_COMPLETED.md` exists, is 473 lines, md5 `af2181c4225ac7d2313c8f0116bba254` — **not** byte-identical to `PRD_FINALIZED.md`/`PRD.md` (both `dc3b6944e0fd41ff9fe1e850a54b17f1`), so the scan demonstrably ran. It retains exactly the original five top-level sections (§1 Introduction line 3, §2 line 11, §3 line 154, §4 line 339, §5 line 420) and ends at a real boundary — the complete final error-table row `| ERR_SHIP_UNITS_EXCEED_ALLOCATION | 422 |` — not mid-sentence.

Note on test validity: Step 9 (and Step 8) edit only PRD documents, never `implementation/`, `test_suite/`, or `test_helpers/`. The Step 7 green state therefore still stands unchanged — `workspace/implementation/results.{1..8}.json`, 95/95 in all 8 rounds.

### Pass A summary (verbatim)

PASS A complete. `PRD_COMPLETED.md` created from `PRD_FINALIZED.md` and patched in the global/cross-cutting layer only.

**Line counts:** PRD_FINALIZED.md 471 lines / 106,120 chars -> PRD_COMPLETED.md 473 lines / 112,389 chars (char delta **+6,244**; one new prose paragraph in §5, everything else in-paragraph inserts; top-level section count unchanged at 5).

**Counts:** 15 ambiguity-pins, 2 mismatch-revisions.

**Changes**
- §2.1 — revise — ambiguity — a missing or whitespace-only `X-User-ID` is now stated to be an `ERR_UNAUTHORIZED` (403), not only a bad `X-User-Role` — web.py:105-110
- §2.1 — revise — mismatch — "the very first gate applied to any request" was a false universal: URL routing precedes it, so an undeclared path/method is answered by §5's routing errors regardless of headers — app.py:20,29-41
- §2.2 — revise — ambiguity — `api_request_id` pinned as `req_` + 20 chars from uppercase letters and digits — web.py:28,42
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time — web.py:48 / db.py:49-50
- §2.2 — insert — ambiguity — a resource field with no value yet is present as JSON `null`, not omitted — derive.py:44-45 (serializers emit every key)
- §2.2 — revise — ambiguity — pagination `meta` keys are absent from every `response_type: "object"` response — web.py:62-79
- §2.3 — revise — ambiguity — `offset` has no upper bound; empty value = omitted; non-integer / `limit` outside 1–100 / negative `offset` -> `ERR_INVALID_REQUEST` (422); these are checked only after a sub-resource path identifier resolves — web.py:156-177, routes_design.py:32+412
- §2.3 — revise — ambiguity — `created_at` ties (the norm under the logical clock) are broken by creation order, so effective ordering is insertion order and "newest first" is that sequence reversed — db.py:75-77, routes_design.py:416
- §2.3 — insert — ambiguity — `total_count` counts filter-matched rows before windowing; `has_more` iff `offset` + returned rows < `total_count` — web.py:66-68,171-177
- §2.5 — insert — ambiguity — every server-recorded timestamp (`created_at`, `updated_at`, `api_request_timestamp`, all `*_at` event stamps) is the logical clock with sub-millisecond precision truncated; client-supplied instants/dates are echoed verbatim while the parsed UTC value is what is compared — db.py:60-66,87-91; validate.py:152-160; routes_design.py:83-84
- §2.6 — insert — ambiguity — rounded values are emitted as JSON numbers (15.50 -> `15.5`, 1.0500 -> `1.05`), and inbound rounding to declared places happens before any bound check — web.py:52-59, prec.py:22-25, validate.py:87-94
- §2.7 — revise — ambiguity — a trailing slash on any path is equivalent to its absence — app.py:20
- §2.7 — insert — ambiguity — filters match by exact equality (unknown/out-of-enum value -> empty page, not an error); empty filter value ignored; boolean filter ignored unless `true/1/yes/false/0/no`; computed-read `basis`-style args are the exception and reject with `ERR_INVALID_REQUEST` — web.py:180-196, routes_design.py:35-46
- §2.8 — insert — ambiguity — requests execute one at a time, so the two optimistic guards close a caller's cross-request read-then-write gap and a passing request completes its whole cascade before another is admitted — web.py:128, db.py:11
- §2.9 — insert — ambiguity — ascending and descending cascade sweeps break `created_at` ties by creation order — db.py:66,75-77 (consistent with cascade.py:26,30, checked by grep)
- §2.11 band 2 — insert — ambiguity — uniform payload-shape rules pinned: body must be valid JSON object (absent/empty = `{}`; undeclared fields ignored); explicit `null` counts as absent; strings non-empty; booleans real JSON booleans; integers JSON numbers with no fractional part (`4.0` ok, `4.5` and numeric strings/booleans refused); numerics rounded before bound tests; RFC 3339 accepts `T` or space and any fractional digits, no offset = UTC, offsets normalized; dates exactly `YYYY-MM-DD` and a real day, months exactly `YYYY-MM` with month 01–12 — validate.py:24-117,120-191; web.py:140-153
- §2.11 band 3 — revise — mismatch — "Two uniqueness rules share this band" undercounted: impl has four `ERR_INVALID_REQUEST` uniqueness rules (`refrigerant_code`, ACTIVE standard per `region_code`, `model_code`, `cell_code`) plus `ERR_DUPLICATE_CERTIFICATION`, all evaluated after identifier resolution — routes_design.py:72-74,156-158,228-230,466-476; routes_ops.py:222-224
- §5 — insert — ambiguity — `ERR_NOT_FOUND` (404) for an unmatched path and `ERR_METHOD_NOT_ALLOWED` (405) for an undeclared method, both outside the catalogue and decided before the role gate, plus the `ERR_INVALID_REQUEST` (422) catch-all — app.py:29-47, errors.py:49-51

**Verified already pinned (no change needed):** the 11-role table matches web.py:14-26 exactly; all 74 impl routes and their authorized-role sets match the §4 table with zero surplus or deficit on either side, and the 13 creating endpoints are exactly those returning 201; the §5 error table matches `ERROR_STATUS` entry-for-entry (45 catalogue ids, identical statuses, every id actually raised somewhere); `id` = unprefixed UUID4, `version` starts at 1 and +1 per mutation, leak/run tests carry neither `updated_at` nor `version` (db.py:60-66,79-84 with `versioned=False` at routes_ops.py:529,606); default clock `2026-08-01T00:00:00Z` and clock-set at `/_clock/set_current_utc` for `PlantAdmin` returning an empty `data` (db.py:13, routes_design.py:51-57); ROUND_HALF_UP everywhere and downward truncation for pool capacity (prec.py:22-48); role gate runs before body parsing, and body parsing before path/FK resolution in every write route, matching the §2.11 band 1->2->3 ladder; internal row keys (`_seq`, cached parsed instants) never leak because every response is built by an explicit serializer.

### Pass B summary (verbatim)

Verified: 473 lines before and after (all edits were in-paragraph), markdown intact.

**Line counts:** 473 -> 473 lines (no line-count change; every edit was an in-paragraph insert or revision). Chars: 112,389 -> 117,965 (**+5,576**).

**Counts:** 18 ambiguity-pins, 8 mismatch-revisions (26 changes).

#### Mismatch-revisions (PRD actively contradicted `implementation/`)

- **§3.4** — revise — mismatch — Cert creation gate order was stated as resolve -> **stale** -> state -> duplicate; impl checks `ERR_DUPLICATE_CERTIFICATION` *before* the stale guard (as §2.11 bands 3/4 already imply). Reordered and made the pairing explicit — `routes_design.py:468-482`
- **§3.4** — revise — mismatch — Salability recomputation trigger list included "submission"; `submit_cert` never touches the platform, so no `version` bump. Dropped it, and added that publishing a regional standard likewise bumps no platform `version` — `routes_design.py:566-571`, `routes_design.py:160-173`
- **§3.4** — revise — mismatch — `rejection_reason` is validated *inside* the `REJECTED` branch, i.e. after the state and SoD gates, contrary to §2.11's band-2-first rule. Pinned as the one conditional shape rule that runs late — `routes_design.py:603`
- **§3.3** — revise — mismatch — Platform-creation gates were enumerated program-resolve -> program-ACTIVE -> supersedes-resolve; impl resolves both FKs and runs `model_code` uniqueness *before* the program-state check — `routes_design.py:225-232`
- **§3.5** — revise — mismatch — `priority_score` was called "the waterfall sort key" and said to "decide who is served first"; it is stored/echoed and **never** read by any computation (grep: only `routes_supply.py:121,137` and `derive.py:319`) — `routes_supply.py:117-121`
- **§3.5** — revise — mismatch — Corollary: "the order in front" is only whichever order the planner draws for first; the server sorts nothing — `calc.py:170-179`
- **§3.6** — revise — mismatch — Ship gates were listed state -> **units** -> deadline -> region; impl order is state -> deadline -> region -> units (§2.11 band 10 last). Reordered and pinned the deadline-before-region tie inside band 7 — `routes_supply.py:284-310`
- **§3.6** — revise — mismatch — Cancel listed ownership before the `PENDING` check; impl checks state first — `routes_supply.py:336-355`

#### Ambiguity-pins

- **§2.8** — insert — With no eligible compressor pool there is no primary row, so the stale guard cannot fire whatever integer is supplied; the draw falls through to the eligibility gate — `routes_supply.py:208-213`
- **§3.2** — insert — `effective_from_utc` is mandatory — `routes_design.py:152`
- **§3.3** — insert — `max_charge_grams` accepts any whole number >= 0 as input; only the review gate demands >= 1 — `routes_design.py:218-220`
- **§3.3** — insert — All six PATCH fields optional; a no-field edit is accepted and still bumps `version` — `routes_design.py:282-315`
- **§3.3** — insert — `revision_notes` mandatory on return-to-draft — `routes_design.py:346`
- **§3.3** — insert — Release is one mutation: `version` +1, not +2 — `routes_design.py:374-376`
- **§3.3** — insert — Retirement `reason` is validated but stored nowhere — `routes_design.py:384`
- **§3.4** — insert — A cert's `region_code` is 1–32 chars with **no** uppercase/underscore restriction (unlike a standard's) — `routes_design.py:463`
- **§3.4** — insert — The governing standard is the region's one ACTIVE standard regardless of whether `effective_from_utc` is reached — `routes_design.py:549-559`
- **§3.4** — insert — Submission mutates only the filing — `routes_design.py:566-571`
- **§3.4** — insert — Cert sub-collection is newest-first, narrowed by `region_code`/`status` only — `routes_design.py:411-417`
- **§3.5** — insert — Supply pools carry no uniqueness constraint at all — `routes_supply.py:33-62`
- **§3.5** — insert — `part_number`/`supplier_lot_code` have no length ceiling — `routes_supply.py:38-39`
- **§3.5** — insert — `distributor_code` has no length ceiling; order `region_code` unrestricted as to character class — `routes_supply.py:117-119`
- **§3.5** — insert — `total_open_demand`'s filter is applied as written, so a preview of an order that no longer matches drops it from its own denominator — `calc.py:137-149`
- **§3.5** — insert — Policy falls back to `PRIORITY_WATERFALL` with no primary; zero `total_open_demand` yields a zero fair share — `calc.py:170-179`
- **§3.5** — insert — Allocation-preview gates nothing (no state, no region, no eligibility refusal); only `policy` is validated — `routes_supply.py:245-266`
- **§3.5 / §3.9** — insert — Line, claim, and CAPA sub-collections narrow by `status` (plus `component_type`/`supplier_lot_code` for claims) only — `routes_supply.py:82-97,358-364`, `routes_design.py:420-428`

#### Checked and already uniquely pinned (no change)

All of `calc.py`'s leak-test limits (3.000 g/yr helium, 2.00 kPa/15 min, 0.500 A2L factor), the run-test 35.0 C / 0.0040 correction, both 3x2 tolerance tables and the 0.90 efficiency floor, `conflicting_run_test`'s strict double-sided cooldown overlap and earliest-`_seq` conflict pick, the 1165 cents/pallet-week carrying-cost math under both bases with `pallet_week_total` identical across them, and `derate_band`/`DERATE_TABLE` — all match §3.7/§3.8/§3.9 exactly, so I left pass C's prose untouched there. Also verified already-pinned: `eligible_pools`' five-part filter, `kit_capacity` = min, `allocated_units` counting compressor lines only, one-line-per-pool draws, `refresh_supply_status`' `derate_pct == 0` condition on `EXHAUSTED -> ACTIVE`, the retirement cascade's two platform touches, and every role list against the §4 table.

### Pass C summary (verbatim)

Pass C complete. Final verification results below.

**Line counts**
- PRD_COMPLETED.md before pass C: **473 lines / 117,965 chars**
- After pass C: **473 lines / 122,470 chars** (char-delta **+4,505**; zero new lines — every change is an in-paragraph insert/revision)

**Counts**
- **ambiguity-pins: 16**
- **mismatch-revisions: 4**

**Changes**
- §2.9 — insert — ambiguity — a row two distinct hops each touch is mutated once per hop, so one request can raise a single row's `version` by more than one — `cascade.py:100-130, 188-196`
- §3.7 — insert — ambiguity — warehouse `name` has no length ceiling; warehouse row carries nothing beyond name/capacity/`pallets_reserved_current`/audit trio; warehouse list takes no filters — `routes_ops.py:42-53`, `derive.py:361-370`
- §3.7 — revise — mismatch — reversed interval is band-2 and therefore reported **ahead of** both not-found errors (PRD's list read as evaluation order); warehouse resolved before build lot — `routes_ops.py:150-157`
- §3.7 — insert — ambiguity — reservation dates need not lie in the clock's future; elapsed days may be booked — `routes_ops.py:150-190`
- §3.7 — insert — ambiguity — omitted `release_reason` is stored as null — `routes_ops.py:205`, `cascade.py:34-44`
- §3.7 — insert — ambiguity — occupancy read: evaluated day is `on_date`, else `window_start`, else the clock's date; `occupancy_units` is that day, `peak_occupancy_units` spans the window only when both bounds are present (equal otherwise); date args must be `YYYY-MM-DD` else `ERR_INVALID_REQUEST`; a non-positive window is not an interval error — `routes_ops.py:72-103`
- §3.7 — insert — ambiguity — carrying-cost read echoes `warehouse_id`, `basis`, `window_start`, `window_end`; a missing bound is `ERR_INVALID_REQUEST`; a non-positive window yields count 0 and zero money — `routes_ops.py:106-129`, `calc.py:200-233`
- §3.8 — insert — ambiguity — `scheduled_start_utc` is echoed only, never compared to clock or cutoff — `routes_ops.py:262, 289`
- §3.8 — insert — ambiguity — start-coil-fab tests stage before platform state; complete-brazing checks platform state not at all — `routes_ops.py:324-343`
- §3.8 — insert — ambiguity — per-lot leak-test read is oldest first and narrows by `method` and `verdict` — `routes_ops.py:423-430`
- §3.8 — insert — ambiguity — an A2L platform with a null `max_charge_grams` refuses every mass; `A1` never consults the field — `routes_ops.py:360-366`
- §3.8 — insert — ambiguity — test cells listable in creation order, filterable by `status` — `routes_ops.py:232-236`
- §3.8 — insert — ambiguity — per-lot run-test read is oldest first, `verdict` only; per-cell read is ascending `window_start_utc` with creation-order ties, `verdict` only — `routes_ops.py:245-252, 433-439`
- §3.8 — insert — ambiguity — omitted cancel `reason` leaves `closed_reason` null; `hold_reason` survives a `HOLD_REGULATORY` cancellation — `routes_ops.py:405-420`
- §3.9 — revise — mismatch — struck the "rolling warranty window" reading `filed_at`/`shipped_at`; the rate is a running rate over the whole counted population with no date window — `derive.py:147-165`
- §3.9 — revise — mismatch — platform is resolved before an optional `build_order_id`, so both-unresolvable reports `ERR_PLATFORM_NOT_FOUND` — `routes_ops.py:744-746`
- §3.9 — revise — mismatch — `counted_claim_count`/`denominator_units` are fields of the warranty-analysis read, not of the platform row — `derive.py:179-207`, `routes_design.py:437-444`
- §3.9 — insert — ambiguity — the filing claim is itself swept, so the POST response already carries `LINKED_TO_CAPA` and `version` 2 — `routes_ops.py:677-682, 763-764`
- §3.9 — insert — ambiguity — hop-3 revocations carry `closed_reason` `SUPPLY_DERATED`; touched pools refresh and may return `EXHAUSTED -> ACTIVE`; the derated pool is bumped a second time, so a cut that revokes lines raises its `version` by two — `routes_ops.py:707-710`, `cascade.py:100-130`
- §3.9 — insert — ambiguity — EFFECTIVE close leaves the pool wholly untouched when another OPEN action still cites it, and lands it in `ACTIVE` even at a zero balance — `routes_ops.py:831-835`
- §3.9 — insert — ambiguity — INEFFECTIVE close bumps the closed pool a second time via the revocation sweep and does not mutate the platform at all — `routes_ops.py:849-854`

**Final check (I am the last pass)**
- File exists at `.../workspace/PRD_COMPLETED.md`
- Valid markdown; backtick parity verified across every edited region; heading set byte-identical to PRD_FINALIZED.md
- Exactly **5 top-level sections** (§1 line 3, §2 line 11, §3 line 154, §4 line 339, §5 line 420)
- Ends at a real boundary: the last complete error-table row `| ERR_SHIP_UNITS_EXCEED_ALLOCATION | 422 |` plus trailing newline — not mid-sentence
- **NOT** byte-identical to PRD_FINALIZED.md (`af2181c4225ac7d2313c8f0116bba254` vs `dc3b6944e0fd41ff9fe1e850a54b17f1`)
- **Final line count: 473. Final md5: `af2181c4225ac7d2313c8f0116bba254`**

Also confirmed clean in-scope: all 27 `routes_ops.py` endpoints match §4's paths, status codes, and authorized-role sets exactly (no role or 200/201 mismatches); all 15 `derive.py` serializers' field shapes are already fully enumerated by §1–§3 prose; leak/run tests correctly carry neither `updated_at` nor `version` per §2.5; the shared two-rework budget, `SCRAPPED`/`REWORK_LIMIT_EXCEEDED`, `BUILD_SCRAPPED` releases, salability's four conditions, `warranty_posture` gates and bands, and the derate table were already pinned uniquely and needed no change.

---

## Pipeline complete — 2026-09-03T05:35:20.866Z

All nine steps finished. Final deliverables in `tasks/task_2495_residential_hvac_equipment_plant/`: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (8 modules), `test_suite/` (13 files, 95 tests), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (13 Python modules + `start.sh` + `requirements.txt`), and `workspace/implementation/results.{1..8}.json` at 95/95.
