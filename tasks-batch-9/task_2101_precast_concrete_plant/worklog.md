# Worklog — task_2101_precast_concrete_plant

## Step 1: Create Task Directory — 2026-08-15T14:59:33.856Z

Created `tasks/task_2101_precast_concrete_plant/` and `tasks/task_2101_precast_concrete_plant/workspace/` via `mkdir -p`. Index and folder name were pre-assigned by the invoking command (no ./tasks/ scan performed).

## Step 2: Generate Scaffold — 2026-08-15T16:02:23.440Z

All three artifacts are generated and pass the skill's own linter.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    60
  §1.1 entities declared:     15
  §1.8 instances scanned:     24
  §1.9 instances scanned:     46
  Calls scanned (§1.8+§1.9):  1045
```

## What was generated

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2101_precast_concrete_plant/`)
- `SCAFFOLD.yaml` (2838 lines) — §1.0–§1.7, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2887 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (3694 lines) — single key `scaffold_corner_design`

**Profile** (above Expert): workflow-orchestration primary / temporal-windowing secondary; layers = cascading side effects, dual-variant calculation, rate/threshold triggers, optimistic concurrency; topology `graph` (incl. `Piece.replaces_piece_id` self edge); shape `parallel`; role model `segregation_of_duties`; `api_prefix: ""` (flat top-level collections, which is what the linter's segment-derivation heuristic needs).

**Seed tables**
- **15 entities**: Project, MixDesign, SteamZone, CastingBed, BedRun, CuringCycle, CylinderSet, CylinderBreak, Piece, YardSlot, YardPlacement, HaulPermit, Shipment, ShipmentLine (`common_fields: false`), RepairDisposition. 20 FKs, all with reverse-reachability GETs.
- **11 state machines**: MixDesign (cyclic QUALIFIED<->SUSPENDED->RETIRED), CastingBed, BedRun (revert edge TENSIONED->SCHEDULED + BLOCKED loop), CuringCycle, CylinderSet (RELEASE_MET<->RELEASE_NOT_MET retest loop), **Piece x 2 parallel dimensions** (`production_status` x `qc_status`), YardPlacement, HaulPermit, Shipment, RepairDisposition (branch at disposition + REINSPECTION<->REPAIR_IN_PROGRESS loop).
- **2 concurrency rules** (OCC only): `ncr-create-stale-piece` (Piece.version, 412), `placement-create-stale-slot` (YardSlot.version, 412).
- **10 calculations**, all literals pre-computed in Python: cylinder break psi; `cylinder_set_qualified_strength` (SET_AVERAGE vs TRIMMED_AVERAGE — 3350 vs 3575 psi on the same three breaks); `curing_energy_accounting` (MODELED 13526c vs METERED 16150c); `strand_jacking_force` (nested `max` floor makes C40->768.00 kips, C60->773.32); `bed_run_cost_allocation` (overhead tier pinned to *direct subtotal* -> 1001390c, vs 967445c under the circular reading); `shipment_permit_fee` (round-per-line 39480c vs sum-then-round 39479c); load metrics; yard occupancy; steam-zone peak concurrent demand; erection load order.
- **16 validation priorities** with explicit intra-priority ordering; segregation-of-duties deliberately ranked at 11, *below* state and safety.
- **60 endpoints** (incl. `POST /_clock/set_current_utc`, default clock `2026-08-01T00:00:00Z`); every one is exercised by at least one design call.
- **53 error codes**, every one triggered by a named design instance.
- **7 roles**: PlantAdmin, ProductionSupervisor, QCTechnician, QualityEngineer, YardForeman, PermitCoordinator (all `opaque`), ProjectOwner (`entity_backed:Project`).

**§1.8** — 24 instances across all nine rules (2/3/3/3/3/3/2/2/3), all above the >=2 minimum. Highlights: 4-hop cascade break->set->run->piece->project; 3-hop reject-recast scrap cascade; three distinct priority-conflict category pairs (safety/referential, state/auth, temporal/fiscal); three boundary metrics on three endpoints (psi `>=`, width `>` , empty valid-specimen set); two different interval geometries (bed pairwise-exclusion-with-buffer vs steam-zone aggregate-capacity sum); three conserved quantities (strand force kips, yard mass lb, held-piece count).

**§1.9** — 66 instances (46 with full recipes + 20 `excluded_because` stubs) across all nine guide sections.

Verified beyond the linter: zero unbound `${var}` placeholders, unique names across both files, no forbidden concurrency vocabulary, every stub resolves to a real §1.8 instance name, all OCC version inputs are `${var}` references, and enum closure (one unreachable error, `ERR_PIECE_ALREADY_ON_SHIPMENT`, was found and removed because the priority-8 state gate always pre-empts it).

## Step 3: Copy Shared Files — 2026-08-15T16:02:23.440Z

Copied `./INSTRUCTION.md` to `tasks/task_2101_precast_concrete_plant/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T16:12:00.000Z

`workspace/PRD.md` generated (428 lines, 96572 bytes) from `SCAFFOLD.yaml` only, with both
`SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` withheld.

NOTE: the pipeline run was interrupted after this artifact was written but before the orchestrator
recorded the subagent's summary, so the doc-generator's verbatim summary is unrecoverable. This entry
is a reconstruction from the on-disk artifact, added when the run resumed at Step 5.

## Step 5: Generate Unit Tests — 2026-08-15T17:04:00.000Z

Test infrastructure and suite generated for `task_2101_precast_concrete_plant`.

## What was produced

**`test_helpers/`** (Stage 1, 9 files)
- `types.py` — 22 status/enum classes + TypedDicts for all 15 entities. `ShipmentLine` correctly omits `updated_at`/`version` (the PRD's single write-once exception).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint; cross-checked programmatically: **60 declared endpoints, 60 implemented, 0 missing, 0 extra**.
- `api_errors.py` — all 53 error IDs + HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, `assert_decimal`/`assert_whole_cents`/`assert_exact_sum` for the PRD's pinned precisions, plus invariant checkers (`assert_slot_occupancy`, `assert_piece_dimensions_status`, `assert_cost_allocation_is_exact`).
- `factories.py`, `constants.py`, `test_users.py` (incl. `make_project_owner_headers(project_id)` for the one `entity_backed:Project` role), `fixtures.py` (~600 lines).
- Key fixture: `setup_production_line(stage=...)` walks the casting cycle through `plant → scheduled → tensioned → curing → release_ready → released → stripped → yarded`, which collapses the design indices' 20–30-call setup chains into one call. Read helpers exist for the five entities with no single-resource GET (curing cycles, breaks, placements, shipment lines, reports) — those go through the collection endpoint the PRD does expose.

**`test_suite/`** (Stage 2) — `conftest.py` + 10 domain-named files, **94 tests**.

## Coverage audit (scripted, against both YAMLs)

- **Queue A (Difficulty):** 24/24 instances, 48 tests — every instance has exactly 2.
- **Queue B (Corner):** 46/46 non-stub instances, 46 tests — every instance has >=1.
- All 20 `excluded_because:` stubs verified to resolve to a real §1.8 instance name; none translated.
- Every docstring ends with exactly one `Design:` line; all tags resolve; no dual-tagged or untagged tests.

## Citation audit (scripted)

Every citation was normalized and literal-matched against `PRD.md`: **0 failures across 94 tests**, all >=8 words. No `pytest.mark.skip`/`skipif`/`xfail` anywhere. No "scaffold"/§1.x references leaked into generated code.

## Adjudication decisions worth flagging

- **No instance was skipped** — all 70 non-stub instances survived the PRD-first two-condition filter. The three `priority_pair_validation_conflict` instances are legitimate because §2.8 enumerates a 16-step refusal order with explicit intra-step ordering, and §2.10 states outright that a request in the wrong state *and* in breach of a duty rule "returns the state error, not the duty error" — so `validate_error_is_one_of` was not needed.
- **Two assertions were dropped** as not uniquely derivable, rather than dropping their tests:
  - `BedRun.piece_count == 1` after a piece is scrapped (`cost_allocation_excludes_scrapped_pieces`). §3.2 pins the `piece_count` recompute to *assign-run only*, and §3.9's four-hop REJECT_RECAST cascade does not list the run among the rows it touches. A faithful PRD-only implementer would leave it at 2.
  - "no Project row is created" after an unauthenticated `POST /projects` — the PRD exposes no `GET /projects` list, so the claim is unobservable. The 401 assertions remain.
- Timestamp equality assertions use `startswith("2026-08-03T06:00:00")` so both `Z` and `.000Z` renderings of client-supplied datetimes pass, while server-stamped instants still verify against the logical clock.

`pytest --collect-only` collects all 94 tests cleanly; everything compiles and imports.

## Step 6: Generate Implementation — 2026-08-15T17:37:00.000Z

Implementation complete and verified.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_2101_precast_concrete_plant/workspace/implementation/` — Python + Flask, in-memory, ~3,200 lines:

- `start.sh` (executable, guarded `pip install`, `exec python3 app.py`), `requirements.txt` (flask 3.0.3)
- `app.py` (blueprints, error handlers, Decimal-aware JSON provider, per-request store lock), `db.py` (store + logical clock + `touch()` mutation bookkeeping), `errors.py` (all 53 error ids + statuses), `response.py`, `auth.py`, `validation.py`, `lookup.py`, `calc.py` (all 10 pinned calculations), `cascade.py`, `serialize.py`, `listing.py`
- `routes/`: `plant.py`, `mix.py`, `runs.py`, `cylinders.py`, `pieces.py`, `yard.py`, `shipping.py`, `repairs.py`

## Verification

Boots in ~0.6 s on a fresh process, binds `0.0.0.0:$PORT` (default 10000), store starts empty (no seeding anywhere). I drove 11 scripted end-to-end batteries against a live server (restarted between each) covering every scenario in `SCAFFOLD_CORNER_DESIGN.yaml` / `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — all pass, including every pinned figure: 768.00/773.32 kips, 35.225/35.469 in, 0.78/0.09 %, 142.38 therms, 13526/16150/15555 cents, 19.40/15.00/15.04 % variance, 3499/3500/3575/3400 psi with `DISCARDED_OUTLIER` rewrites, 486136->593086 and 848636->1001390 cent allocations splitting 333798/333796/333796, permit fees 1740/11980/37740, and the conserved-quantity baselines (bed force, yard weight, held-piece count). A programmatic diff confirms all 60 scaffold endpoints exist with zero extras and RBAC matching the role table exactly for all 7 roles x 60 endpoints.

## Two judgement calls worth flagging

1. **`created_at`/`updated_at`/`api_request_timestamp` read the logical clock**, not wall time (PRD §2.4 "every instant it stamps... is read from that clock"). Lists sort by `created_at` with an internal insertion sequence as tiebreak, so ordering stays insertion-stable while the clock is frozen. `POST /_clock/set_current_utc` returns the canonical `...000Z` form.
2. **Intra-priority ordering conflicts resolved in favour of §2.8** where it declares a fixed order (elongation gate at step 10 before strand capacity at step 13), and in favour of the §3 narrative where §2.8 does not (tension checks bed `AVAILABLE` before mix `QUALIFIED`; that combination is unreachable anyway, since suspending a mix blocks its `SCHEDULED` runs).

Derived counters (project counters, `piece_count`, `committed_strand_force_kips`, `cumulative_cycle_count`, slot occupancy, shipment metrics, `repair_count`, line surcharges) are recomputed live on read, while `updated_at`/`version` bumps follow the PRD's enumerated cascade hops literally — one bump per row per request.

**ORCHESTRATOR NOTE (not from the subagent):** the Step 6 summary states the subagent read
`SCAFFOLD_CORNER_DESIGN.yaml` / `SCAFFOLD_DIFFICULTY_DESIGN.yaml` during its self-verification. The
entrance skill's Step 6 prompt lists only INSTRUCTION.md / SCAFFOLD.yaml / PRD.md as inputs and, unlike
Step 4, carries no hard constraint forbidding the design indices — so this was not a violation of the
prompt as written, but it does mean the reference implementation was validated with sight of the
test-targeting indices. Recorded here for pipeline-hygiene follow-up.

## Step 7: Run Tests and Iterate — 2026-08-15T17:41:00.000Z

The exit condition was met on the first iteration — no fixes were needed.

## Summary

**Iterations run:** 1 (baseline 8-round parallel sweep, no follow-up rounds required)

All 8 concurrent rounds ran to completion and each reported `94/94 passed, 0 failed, 0 errors, 0 skipped`. Verified by reading all eight `results.${i}.json` files directly, not just the console tails:

```
results.1.json … results.8.json:  passed=94 total=94 failed=0 errors=0 skipped=0
```

Wall time ~121 s per round under `--isolation per-test-server` (94 server reboots x 8 concurrent rounds); the runner's file-locked port registry handed out 8 distinct ports (36815, 60109, 41485, 45195, 34673, 59141, 52905, 36007) with no collisions.

**Tests deleted:** none. No test failed in any round, so STEP 1's coverage / unique-derivability filter never had to be applied.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

### Findings from the audit performed alongside the sweep

- **No flakiness signal.** The union of failing tests across all 8 rounds is empty. The suite contains zero concurrency-race tests (`grep` for `run_race`, `assert_race_outcome`, `assert_exactly_one_succeeds`, `threading` over `test_suite/` returns nothing) — the two OCC rules in the PRD (`ERR_STALE_PIECE_VERSION`, `ERR_STALE_YARD_SLOT_VERSION`) are exercised sequentially via stale expected-version values rather than by racing requests, which removes the main class of timing-sensitive bug this sweep is designed to catch.
- **Cardinal-rule compliance verified, not assumed:**
  - No `pytest.mark.skip` / `skipif` / `xfail` anywhere in `test_suite/` or `test_helpers/`.
  - `workspace/implementation/` has no `sqlite`, file `open(`, `json.dump`, `/tmp/`, `pickle`, `shelve`, or external-store usage — storage is pure in-memory dicts in `.../implementation/db.py` (`Store.__init__` allocates 15 empty dicts), so every `start.sh` reboot under per-test-server isolation wipes all state.
  - No startup seeding: `Store.__init__` sets only empty collections plus the logical clock at the PRD-declared default `2026-08-01T00:00:00Z` (PRD §2.4: "Before the first clock call of a server's life, the clock reads exactly `2026-08-01T00:00:00Z`"), which is a system constant, not entity data.
- **`start.sh` already carries a boot-contention guard** that matters for this sweep specifically: it skips `pip install` when Flask imports cleanly, with an inline comment noting that an unconditional install causes flaky "could not be restarted" timeouts when 8 rounds reboot the server concurrently. That guard is why 752 server boots (94 x 8) completed without a restart failure.

**Working tree unchanged** — `git status` reports no modifications under the task directory, since I applied no edits.

Relevant paths:
- `.../workspace/implementation/results.1.json` … `results.8.json` (sweep evidence, left in place)
- `.../workspace/implementation/start.sh`
- `.../workspace/implementation/db.py`

**ORCHESTRATOR VERIFICATION (not from the subagent):** independently re-read all 8 `results.*.json`
files — every one reports `passed=94 total=94 failed=0 errors=0 skipped=0`. Independently confirmed
zero `mark.skip` / `mark.xfail` / `skipif` occurrences across `test_suite/` and `test_helpers/`, and 94
`def test_` functions on disk (matching the reported total, so nothing passed by not being collected).

## Step 8: Finalize PRD — SKIPPED — 2026-08-15T17:42:00.000Z

Skip condition met per the skill: Step 7 exited on its first 8-round sweep with 0 test deletions,
0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond
the baseline. There is no `<step_7_diff>` to hand off, so no subagent was spawned and
`workspace/PRD_FINALIZED.md` is intentionally absent. Step 9 therefore starts from `workspace/PRD.md`.

CAVEAT worth carrying forward: because Step 7 produced no failure signal at all, it surfaced zero
evidence about where `PRD.md` under-determines behaviour. Step 9's full PRD-vs-implementation scan is
consequently the ONLY completeness check this run performs. See also the Step 6 note about the
implementation generator having read the design indices during self-verification — that plausibly
explains the first-sweep pass and further reduces how much independent signal Step 7 carried.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-08-16T03:55:45.382Z

**RESUME NOTE (orchestrator).** The prior run of this pipeline was terminated by an account session
limit one second after Step 9's subagent executed its `cp PRD.md PRD_COMPLETED.md` (Method step 0),
so the `PRD_COMPLETED.md` found on disk at resume time was byte-identical to `PRD.md`
(md5 `b4ad6e32712ccb73e4e234b119c07f66` on both) — a partial artifact from an interrupted run, not a
finished Step 9 output. It was deleted and Step 9 was re-run from scratch with a full
PRD-vs-`implementation/` scan. Steps 1-8 were NOT re-run: their artifacts were verified present on
disk and left untouched. Step 8 remains correctly skipped, so Step 9's source file was
`workspace/PRD.md`.

### Subagent summary (verbatim)

`workspace/PRD_COMPLETED.md` is written. Full exhaustive scan of all 21 implementation files (3,174 lines) against `workspace/PRD.md`; 36 minimal inline edits applied, no new sections, all 5 top-level sections intact.

## Summary

**Files** — source `PRD.md`: 428 lines / 96,254 chars (96,572 bytes). Result `PRD_COMPLETED.md`: **430 lines** / 105,378 chars (105,738 bytes). Char delta **+9,124** (+9,166 bytes). Only 2 lines added (both new rows in the §5 error table); every other change is an in-paragraph insert or revision.

**Counts** — ambiguity-pins: **28**. mismatch-revisions: **8**.

### Mismatch revisions (PRD described behavior impl does not exhibit)

- §3.7 — revise — mismatch — PRD required the slot's `status` to be `EMPTY` or `PARTIAL`; impl refuses only `BLOCKED` at step 9, and a `FULL` slot is turned away by the step-13 weight/stack gates instead — `routes/yard.py:38-47`
- §3.5 — revise — mismatch — break preconditions were prose-ordered specimen-limit-first; impl judges the run's `STRIPPED` state (step 8) before the specimen limit (step 13) — `routes/cylinders.py:71-79`
- §2.8 step 9 — revise — mismatch — prose listed mix-qualification before bed-availability; at tensioning impl checks the bed first, so `ERR_PLANT_RESOURCE_UNAVAILABLE` wins over `ERR_MIX_DESIGN_NOT_QUALIFIED` — `routes/runs.py:109-114`
- §3.3 — revise — mismatch — "the only way a bed is ever unavailable at registration is … `DOWN`" was false: the optional `status` accepts all three of `AVAILABLE`/`OCCUPIED`/`DOWN` and stores what it is given — `routes/plant.py:119`
- §3.7 — revise — mismatch — PRD said `LOAD`/`SCRAP` pulls are "driven by the workflows … rather than by an explicit pull request"; an explicit pull performs the same piece transition, writes only `production_status`, and only when the piece is `YARDED` — `routes/yard.py:80-90`
- §3.9 — revise — mismatch — `REJECT_RECAST` "reachable from PLANNED…YARDED" implied a guard; impl enforces no production-status precondition and scraps from whatever status the piece holds — `cascade.py:76-85`
- §3.8 — revise — mismatch — "the two-letter `issuing_state`" implied a length rule; impl validates it only as a non-empty string — `routes/shipping.py:30`
- §4 table — revise — mismatch — `/pieces/{id}/shipment-lines` was called "the reverse view the already-loaded check reads"; the load gate reads the piece's own `production_status` — `routes/shipping.py:151`

### Ambiguity pins (PRD silent)

- §2.1 — insert — ambiguity — "Any" on a GET means the seven named roles only; any other role string → `ERR_UNAUTHORIZED` — `auth.py:31-33`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 upper-case-alphanumeric chars — `response.py:18-19`
- §2.2 — insert — ambiguity — `has_more` = `offset + len(items) < total_count`; pagination meta on list endpoints only — `response.py:40-50`
- §2.3 — insert — ambiguity — non-integer / out-of-range `limit` or negative `offset` → `ERR_VALIDATION` judged at step 5 (so 404 still wins); empty string = omitted; `offset ≥ total_count` yields an empty array — `validation.py:184-208`
- §2.3 — insert — ambiguity — `created_at` ties are broken by insertion order (rows share a `created_at` under a static logical clock) — `db.py:137-139`
- §2.3 — insert — ambiguity — filters match by exact string equality, empty-string filter = absent, non-matching value yields an empty page not an error, undeclared query params ignored — `validation.py:211-215`
- §2.4 — insert — ambiguity — `current_utc` is rendered in the three-fractional-digit UTC form; non-UTC `to_iso8601` offsets are converted; unparseable → `ERR_VALIDATION` — `routes/plant.py:21-27`
- §2.5 — insert — ambiguity — `updated_at` equals `created_at` at creation; all stored/echoed instants are normalised to 3-digit UTC, `erection_start_date` excepted — `db.py:45-48,91-101`, `routes/runs.py:46-47`
- §2.5 — insert — ambiguity — a row touched several times in one request increments `version` by exactly 1; a row created by the request stays at `version` 1 even when a later hop rewrites it — `db.py:104-134`
- §2.6 — insert — ambiguity — multiple body references resolve in the order the §3 narrative names them (bed→mix, project→mix→superseded piece, piece→slot, project→permit) — `routes/runs.py:33-34`, `routes/pieces.py:33-36`, `routes/yard.py:29-30`, `routes/shipping.py:104-106`
- §2.6 — insert — ambiguity — unmatched route or method → 404 `ERR_NOT_FOUND`; trailing slash insignificant; unexpected failure → 500 `ERR_INTERNAL` — `app.py:40,69-81`
- §2.7 — insert — ambiguity — numerics are JSON numbers, never quoted strings — `app.py:26-33`
- §2.8 step 5 — insert — ambiguity — non-JSON / non-object body → `ERR_VALIDATION`; blank body = `{}`; explicit `null` counts as absent for both required and optional fields; coded/identifier strings must be non-empty (only mix `code` has a ceiling) while `reason`/`description` may be empty; the eleven body-less endpoints ignore anything sent — `validation.py:23-58,128-131`
- §3.1 — insert — ambiguity — `design_28day_psi`, `required_release_psi`, `cement_lb_per_cy`, `unit_cost_cents_per_cy` are integers; only `w_c_ratio` is decimal — `routes/mix.py:27-34`
- §3.2 — insert — ambiguity — `erection_sequence_no` is an integer; the five measurements are decimals — `routes/pieces.py:25-30`
- §3.2 — insert — ambiguity — `replaces_piece_id` need only exist: no same-project, scrapped, or unclaimed constraint — `routes/pieces.py:35-36`
- §3.3 — insert — ambiguity — `strand_count` integer > 0; `strand_diameter_in` off-set value → `ERR_VALIDATION`; `measured_elongation_in` is range-unchecked (zero/negative accepted by the schema) — `routes/runs.py:99-102`
- §3.4 — insert — ambiguity — a curing cycle may be scheduled against a run in any status, including `STRIPPED` — `routes/runs.py:286-300`
- §3.4 — insert — ambiguity — `metered_therms` is range-unconstrained and is itself rounded half up to 2 dp before storage, `energy_therms` and the variance — `routes/runs.py:348`, `calc.py:137-142`
- §3.5 — insert — ambiguity — a cylinder set may be cast against a run in any status, even `STRIPPED` — `routes/cylinders.py:19-28`
- §3.5 — insert — ambiguity — with several `RELEASE` sets the gates pass on *any* of them, and the duty check runs against the earliest-created qualifying set — `routes/runs.py:223-245`
- §3.6 — insert — ambiguity — a strip finding zero `CAST` pieces still writes all eight cost fields (volume/concrete = 0) and allocates nothing — `calc.py:255-261`
- §3.7 — insert — ambiguity — `stack_level` is an integer ≥ 1 recorded for reference only; not unique, not contiguous, no part in occupancy — `routes/yard.py:26`
- §3.7 — insert — ambiguity — the seeded slot `status` accepts all four enum values but only `BLOCKED` survives the recompute — `routes/plant.py:156-168`
- §3.8 — insert — ambiguity — a linked `haul_permit_id` need only exist; no project match, no status requirement at link time — `routes/shipping.py:100-106`
- §3.8 — insert — ambiguity — a clock before `valid_from` also yields `ERR_PERMIT_EXPIRED` but leaves the permit `ISSUED`; the past-`valid_to` move to `EXPIRED` survives the rejected request — `routes/shipping.py:216-222`
- §3.9 — insert — ambiguity — closing a report (`USE_AS_IS` or passing reinspection) against a piece that is no longer `NONCONFORMING` leaves `qc_status`/`qc_hold_reason` alone and only recounts the project — `cascade.py:88-94`
- §3.9 — insert — ambiguity — a failing reinspection below the limit retains `repaired_by_user_id` (no second start-repair is reachable from `REPAIR_IN_PROGRESS`) — `routes/repairs.py:145-148`
- §5 — insert — ambiguity — added `ERR_NOT_FOUND` (404) and `ERR_INTERNAL` (500) rows so the catalogue covers every error id the server can emit — `app.py:69-81`

### Verified-conformant (scanned, no change needed)

All 61 endpoints and their role bindings match §4 exactly; the §2.8 16-step refusal ladder matches every handler's check order; every pinned formula in `calc.py` (`cylinder_break_strength_psi`, `cylinder_set_qualified_strength` with both variants and the single-pass band, `curing_energy_accounting` incl. the worked 142.38/13526/16150/19.40 example, `steam_zone_peak_concurrent_demand`, bed occupancy with turnaround buffer, `strand_jacking_force` with the 32.0-kip floor, `bed_run_cost_allocation` with floor-share + remainder-to-first, `yard_slot_occupancy`, `shipment_load_metrics`, per-line-rounded `shipment_permit_fee`) reproduces the PRD arithmetic and rounding order exactly; all §5 error-id→HTTP mappings match `errors.py`; the derived counters on `Project`, `CastingBed`, `BedRun`, `CylinderSet`, `YardSlot`, `Shipment` and `Piece` recompute as §2.11 requires; and `ShipmentLine` alone omits `updated_at`/`version` per §2.5.

### ORCHESTRATOR VERIFICATION (not from the subagent)

- `PRD_COMPLETED.md` exists at 430 lines / 105,738 bytes and is NO LONGER identical to `PRD.md`
  (428 lines / 96,572 bytes) — the interrupted run's byte-identical artifact has genuinely been replaced.
- All 5 top-level `##` sections are present and at IDENTICAL line numbers in both files
  (3 / 11 / 163 / 305 / 372: Introduction, Global Specifications, Business Logic & Workflows,
  Endpoint Definitions, Error Code Catalogue) — no section was added, removed, or displaced.
- `diff PRD.md PRD_COMPLETED.md` yields 33 hunks: 32 in-place `c` (change) hunks and exactly one `a`
  (append) hunk adding 2 lines at EOF. Grep for delete-only (`Nd`) hunks returns NONE — no PRD prose
  was dropped. This matches the skill's "minimal patch, in-paragraph edits, no new sections" mandate.
- The 2 appended lines are well-formed markdown table rows continuing the §5 error catalogue
  (`ERR_NOT_FOUND` → 404, `ERR_INTERNAL` → 500).
- Zero scaffold leakage: grep for `scaffold` / `test_recipe` / `difficulty_design` / `corner_design`
  in `PRD_COMPLETED.md` returns 0 hits, consistent with the subagent's MUST-NOT-READ constraint.
- Spot-checked 4 of the subagent's cited impl anchors directly against source rather than trusting the
  report: `app.py:69-81` (404/405 → `ERR_NOT_FOUND`, catch-all → `ERR_INTERNAL`) CONFIRMED;
  `routes/yard.py:38-47` (only `BLOCKED` refused, weight/stack gates follow) CONFIRMED;
  `routes/shipping.py:30` (`issuing_state` is `req_str`, no length constraint) CONFIRMED;
  `routes/plant.py:119` (`opt_enum(..., BED_STATUSES, "AVAILABLE")` — accepts all three, stores what
  it is given) CONFIRMED. No hallucinated anchors found in the sample.
- `find . -newermt 2026-08-16` over the task directory returns EXACTLY one file:
  `workspace/PRD_COMPLETED.md`. Step 9 wrote nothing else — `PRD.md`, `test_helpers/`, `test_suite/`,
  `workspace/implementation/` and the 8 `results.*.json` sweep artifacts are all bit-for-bit as Step 7
  left them, so Step 9 did not invalidate Step 7's passing evidence.

### Judgement calls made autonomously (no user available; `claude -p` non-interactive)

1. **Treated the pre-existing `PRD_COMPLETED.md` as untrusted and deleted it.** It was byte-identical
   to `PRD.md`, which is exactly the state Method step 0 produces before any scanning work — and the
   interrupted run left no worklog entry to claim otherwise. Keeping it would have silently recorded a
   never-performed scan as a completed step. Regenerating cost one subagent run; trusting it risked
   shipping an uncompleted deliverable.
2. **Did not re-run Steps 1-8.** All their artifacts verified present on disk; the 8 `results.*.json`
   files independently re-confirm 94/94 in every round. Re-running would have burned budget and risked
   perturbing a verified-passing state.
3. **Did not re-run the test sweep after Step 9.** Step 9 touches only `PRD_COMPLETED.md`, which no
   test imports and no implementation reads; the `find -newermt` check above proves nothing else moved,
   so Step 7's evidence still holds without re-execution.
4. **Accepted the 8 mismatch-revisions as legitimate.** A mismatch means PRD prose described behavior
   the impl does not exhibit. Step 7 could not have caught any of these: they sit on paths the 94-test
   suite either does not assert (e.g. `FULL`-slot handling, `issuing_state` length, explicit yard pull)
   or asserts only in the direction impl already implements. This is precisely the residual-gap class
   Step 9 exists to close, and it vindicates the Step 8 caveat that a zero-fix Step 7 carries no
   completeness signal.

**PIPELINE COMPLETE.** All 9 steps are done: Steps 1-7 executed, Step 8 correctly skipped, Step 9
executed here. Final deliverable set is on disk.
