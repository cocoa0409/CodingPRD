# Worklog — task_2148_water_taxi_harbor_shuttle

## Step 1: Create task directory — 2026-08-24T14:32:42.511Z

Created `./tasks/task_2148_water_taxi_harbor_shuttle/` and `./tasks/task_2148_water_taxi_harbor_shuttle/workspace/`.

## Step 2: Generate scaffold — 2026-08-24T15:33:11.000Z

All three scaffold artifacts are generated, self-consistent, and lint-clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2148_water_taxi_harbor_shuttle/`
- **`SCAFFOLD.yaml`** (2,444 lines) — §1.0–§1.7 plus `concurrency_rules`, `invariants`, `validation_priority_conflicts`
- **`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (2,039 lines) — 9 rule blocks / 19 instances
- **`SCAFFOLD_CORNER_DESIGN.yaml`** (~3,600 lines) — 9 sections / 60 instances (54 live + 6 `excluded_because` stubs)

## Design

Expert-plus band: **12 entities, 37 endpoints, 44 errors, 12 calculations, 9 state machines, 26 ordered validations, 6 roles, 2 OCC rules, 3 conserved-quantity invariants.** Profile: `temporal_windowing` x `posture_driven_gating`, **flat** topology, **parallel** state-machine shape, **segregation_of_duties** role model, `api_prefix: /harbor`, logical clock defaulting to `2026-08-01T00:00:00Z`.

Coupling that carries the difficulty:
- **Trip has two independent state axes** (`operational_status` x `settlement_status`) written by the same endpoints but asserted separately; `Booking` is cyclic (OFFERED->REQUESTED, bounded at `offer_round` 3); `ServiceDay.posture` is a cyclic derived gate; `RidePass` cycles EXHAUSTED->ACTIVE.
- **Two deliberately different interval geometries**: `Dock` uses half-open instants + a symmetric turnaround buffer + aggregate `berth_count`; `Vessel` layup uses closed-closed calendar dates with single occupancy — touching an endpoint conflicts on one and not the other.
- **Landing fees are posted provisionally at departure and reversed-then-reposted at completion**, with a pinned 6-step evaluation order (reverse -> read pre-posting accrual -> select rebate tier -> compute -> accrue -> cap). This makes `Dock.accrued_fee_cents` a conserved quantity that only balances if the compensating reversal runs; skipping it leaves 4120 instead of 2960 while every endpoint still returns 200.
- **Two dual-variant calcs on different domains** (dock fee PROVISIONAL 1400 vs FINAL 1760; ride-pass residual PRO_RATA 5400 vs DIFFERENTIAL 4600), **three combinatorial modes** (min-of-three-ceilings capacity, round-per-seat fare 3807-vs-3806, rebate-tier circular dependency 92000), **two 3+-hop cascades from different triggers**, **three priority-conflict pairs**, and boundary pins at clearance exactly 0.30 m, wind exactly 22.0/35.0 kn, low water exactly 1.80 m, attendance exactly 15000/30000, and the empty dispatch pool.

## Verification performed

- `scaffold_lint.py` -> **`VERDICT: clean lint`** (37 endpoints, 12 entities, 19 §1.8 + 54 §1.9 instances, 840 calls scanned, all FKs reverse-reachable).
- Every formula-derived assert literal was computed in Python against the scaffold's own formulas and constants before being written.
- Independent audits: 79/79 unique instance names, zero unbound `${var}`, zero dangling `grounds` refs, all 6 stub targets resolve, all 44 errors and all 12 calculations exercised, no forbidden concurrency vocabulary, and an ownership replay confirming the only actor/owner mismatches are the two deliberate `ERR_NOT_RESOURCE_OWNER` negative tests.
- Two bugs caught and fixed during generation: a ladder-masking trap (the pass-zone-vs-rides conflict would have tripped `ERR_PASS_NOT_ACTIVE` first if the pass had been driven to EXHAUSTED), and an unobservable cap cascade link (reworked to a `rebate_bp` pre-lock on sibling reserved slots so the third hop is assertable without breaking the fee invariant).

## Step 3: Copy shared files — 2026-08-24T14:32:55.000Z

Copied `./INSTRUCTION.md` -> `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-24T15:43:20.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2148_water_taxi_harbor_shuttle/workspace/PRD.md` — 370 lines, ~11,100 words, written incrementally across six appends so nothing was truncated. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Structure**: §1 Introduction (3 paragraphs) -> §2 with 10 domain-derived subsections (RBAC, fixed response envelope, pagination, identity/versioning, logical clock, money & basis points, OCC, the 26-rung rejection ladder, conserved quantities, cascade propagation) -> §3 with 9 workflow subsections (estate setup, operating-day posture/surge, trip planning & capacity, shared-dock berths, passes & frozen fare, dispatch/decline/confirm, movement, fee posting variants, shutdown/refunds) -> §4 4-column endpoint table -> §5 2-column error table. Document ends at §5 with no audit footer.

**Completeness counts (grepped from the finished PRD)**:
- Endpoints: 37/37 rows in §4, every scaffold `path` present verbatim
- Errors: 44/44 rows in §5, and all 44 IDs also mentioned in §2/§3 prose with their trigger conditions
- Calculations: 12/12 expressed as precise prose (anchor-constant check passed for all: 35.0/22.0/2.50/1.20/1.80 posture thresholds, 15000/30000 surge floors with 10000/12500/15000 bp, 70%/24/12/0.60 capacity terms, 450+275 and 14000 bp fare terms, 200000/500000 rebate floors with 800/1500 bp, 1100/1800/2600 retail per-ride, 5000 bp partial leg + 5000-cent cash cap, dispatch ranking + tie-breaks, seats aggregation, 365-day inspection validity, berth buffer/`berth_count` occupancy count, closed-closed layup overlap)
- State machines: 9/9, all 38 transitions present as explicit `FROM -> TO` backticked pairs

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 102 required, 102 present, 0 missing
- endpoints[].request_body/input: 64 required (body + query + path identifiers), 64 present, 0 missing
- endpoints[].query_params: included in the 64 above (limit, offset, and all filter params), 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 26 checked, 26 expressed in prose (§2.8 renders the full ascending ladder plus all 3 validation_priority_conflicts), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (POST /harbor/trips/{id}/dock-slots + expected_dock_version + ERR_STALE_DOCK_VERSION 412; POST /harbor/bookings/{id}/confirm + expected_trip_version + ERR_STALE_TRIP_VERSION 412), 0 missing
- state_machines[].transitions: 38 checked, 38 fully expressed with preconditions, error IDs and side effects, 0 missing
- calculations[]: 12 checked, 12 fully expressed (constants embedded, pinned evaluation orders and boundary inclusivity preserved, no pseudocode, no fuzzy words), 0 missing
- validations[] conditions: 26 checked, 26 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 37 endpoints checked, all side effects and all applies_to scopes expressed, 0 missing
- entities[].fields[] structured content: 102 checked, defaults/initial values/enum members/ranges reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (SCHEDULED/BOARDING->CANCELLED, decline->REQUESTED vs ->UNFULFILLED, ACTIVE/EXHAUSTED->REFUNDED, PROVISIONAL vs FINAL posting, PRO_RATA vs DIFFERENTIAL, APPROVE vs DENY, all six posture edges, all four vessel service_state edges), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 730
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 matches `section-2.2-response-structure.md` byte-for-byte; §2.3 states limit default 10 / min 1 / max 100, offset default 0, `created_at` ascending sort (with the one declared exception for the inspection listing); the three invariants (ride-credit, dock-fee, seat-commitment) are stated as conserved identities; and `VesselInspection` is explicitly called out as carrying only `id` and `created_at`.

**Orchestrator verification**: 370 lines; §4 table has 37 method rows matching 37 scaffold paths; §5 has 44 ERR rows; file terminates mid-table-free at the final error row — no truncation.

## Step 6: Generate implementation — 2026-08-24T16:05:15.000Z

(Ran concurrently with Step 5; Step 5's entry follows below.)

Implementation is complete and verified.

## What was built

`workspace/implementation/` — Python + Flask, 13 modules plus `start.sh` and `requirements.txt`:

- `start.sh` — guarded `pip install` (skipped when Flask is importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` (blueprints, error handlers, request lock), `store.py` (in-memory dicts + logical clock), `errors.py` (44-error catalogue), `envelope.py`, `auth.py`, `validation.py`, `calc.py`, `cascades.py`, `serialize.py`, and four route modules (`routes_estate`, `routes_days`, `routes_trips`, `routes_bookings`, `routes_claims`)

All **37 endpoints** from PRD §4 are registered (verified against the URL map). Storage is Python dicts only — no SQLite, no disk writes, no seeding at import or boot.

## Verification

Three smoke suites (137 assertions) run against a fresh `bash start.sh` boot, all passing: full happy path (estate -> day -> trip -> berth -> booking -> board/depart/complete), posture/surge boundaries, capacity derates (posture/tide/crew ceilings + standing bonus + hard cap), berth-buffer overlap geometry, layup overlap (closed-closed) vs. berth overlap (half-open), OCC on both dock and trip, dispatch/decline/UNFULFILLED cycle, pass redemption/exhaustion/restoration, Cascade A, interruption + refund-claim waterfall + segregation of duties + interruption bubble-up, fee reversal/re-post + cap flip with fee trimming, and pro-rata/differential pass refunds.

## Two PRD internal contradictions I had to adjudicate — worth flagging

1. **Confirm-endpoint check order.** §2.8's ladder puts `ERR_PASS_NOT_ACTIVE` at rung 10 (state), but §2.8's own worked example says *"an INNER pass with zero rides left, tendered for a three-zone hop, is rejected with `ERR_PASS_ZONE_NOT_COVERED`"* — a pass with zero rides is necessarily `EXHAUSTED`, so a rung-10 status check would mask that outcome and contradict the stated result. §3.6 lists the pass checks as zone -> expired -> status -> rides. I followed §2.8 everywhere except moving the confirm-time pass-status check below zone coverage — the minimal deviation that makes the documented example reachable. Everything else on confirm follows §2.8 rung order (OCC -> suspended -> expired -> zone -> status -> capacity -> rides), including capacity(25) before rides(26) where §3.6 says the reverse.

2. **`seats_committed` after completion.** §2.9 states the identity holds "always", but the `trip_seats_committed` trigger list omits completion. Since completion moves bookings `BOARDED -> COMPLETED`, I recompute at completion (dropping it to 0) to preserve the stated invariant.

Also noted: `PATCH /service-days/{id}` fires Cascade A whenever the *resulting* posture is `SUSPENDED` (a superset of the two documented edges, idempotent in the common case).

**Orchestrator verification**: 16 files present in `implementation/` (2404 lines of Python + start.sh + requirements.txt); grep for seed/preload/demo-data found only a docstring stating nothing is seeded.

## Step 5: Generate unit tests — 2026-08-24T16:32:40.000Z

(Ran concurrently with Step 6; Step 6's entry appears above.)

Test infrastructure and suite are complete.

## What was generated

**`test_helpers/`** (9 modules, ~1,300 lines)
- `types.py` — 20 status/role enums + 12 entity TypedDicts. `VesselInspection` correctly omits `updated_at`/`version` (`common_fields: false`); the other 11 carry the full set.
- `api_client.py` — 37 endpoint methods, one per PRD route, including `POST /_clock/set_current_utc`.
- `api_errors.py` — all 44 error ids + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — 12 per-entity assertions plus the three conserved-quantity checkers from PRD §2.9 (`assert_dock_fee_conservation`, `assert_ride_credit_conservation`, `assert_seat_commitment`).
- `test_users.py` — shared role headers plus `make_vessel_master_headers(crew_id)` (the one `entity_backed` role; every movement call threads the real `CrewMember.id`).
- `fixtures.py` — `setup_harbor_world(...)` builds the recurring two-dock / two-stop / vessel / master / inspection / operating-day / clock preamble that ~50 of the 73 design instances share, with per-field overrides; then tiers for sailings, berths, bookings, the board->depart->complete lifecycle, and the suspension->interruption->claim chain.

**`test_suite/`** — `conftest.py` + 10 domain-named test files, **92 test functions (97 collected cases)**.

## Coverage against the two design indices
- **Queue A (difficulty)**: 19/19 instances, each with exactly 2 tests -> 38 tests.
- **Queue B (corner)**: 54/54 live instances, 1 test each -> 54 tests. The 6 `excluded_because:` stubs were verified to cross-reference real difficulty instances and were **not** translated.
- **Zero instances skipped** — every one passed the PRD-first coverage + unique-derivability filter. This PRD states each rule explicitly (the §2.8 rejection ladder even spells out the three precedence pairs, and §2.9 states the conserved identities), so no gaps had to be logged.

## Audit results (scripted, all green)
- Every docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real instance; no untagged, dual-tagged, or stub-pointing tests.
- Every quoted PRD citation was checked verbatim against a whitespace-normalised `PRD.md` — **0 mismatches** (one initial failure, a dropped `**Cascade A**` bold marker, was fixed).
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere.
- No scaffold vocabulary leaks into generated comments or docstrings.
- `pytest --collect-only` succeeds (97 cases); `pyflakes` clean.

All expected values are copied verbatim from the design indices rather than recomputed — e.g. the 1400-vs-1760 provisional/final divergence, 3807-not-3806 fare rounding, the 800 bp rebate keyed on the 300000 pre-posting accrual, the 1500-cent cap trim plus the 10000 bp sibling pre-lock, and the 2960-cent dock conservation identity.

**Orchestrator verification**: 9 test_helpers modules + conftest.py + 10 test files; 92 `def test_` functions, 92 `Design:` tags (1:1).

## Step 7: Run tests and iterate — 2026-08-24T16:38:35.000Z

All 8 parallel rounds passed on the first sweep. Exiting.

## Summary

**Iterations run:** 1 (one 8-round parallel stability sweep). All 8 rounds returned `passed == total == 97`, `failed == 0`, `errors == 0`. Confirmed twice — once by reading `results.1..8.json` directly and once by an independent monitor pass over the same files.

**Tests deleted:** none. No test failed in any round, so no test reached STEP 1 of the diagnostic protocol. Nothing was weakened, skipped, or relaxed.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none required.

### Notes on the two flagged PRD contradictions

I audited both areas the implementation generator flagged, since a lucky-round pass on a contradiction is exactly the failure mode the sweep is meant to catch. Both turned out to be un-exercised by the suite rather than silently mis-resolved:

1. **Confirm-endpoint pass-check ordering.** §2.8's ladder puts `ERR_PASS_NOT_ACTIVE` at rung 10 and `ERR_PASS_EXPIRED` at rung 20, both above zone coverage at rung 22; §3.6's prose puts zone coverage first, then expiry, then status. `workspace/implementation/routes_bookings.py:284-306` follows the §2.8 ladder (expired -> zone -> not-active -> no-rides). The suite never constructs a pass that is simultaneously expired/inactive *and* zone-uncovered: `test_tendering_a_stale_pass_expires_it_and_rejects_the_confirmation` uses a zone-covered `INNER` pass on a 1-zone hop, and `_zone_and_balance_world` uses a live `ACTIVE` pass on a 3-zone hop. The contradiction is therefore latent, not observable, and no test asserts a uniquely-derivable outcome across the disputed rungs — nothing to adjudicate.

2. **`seats_committed` recomputation at completion.** `routes_trips.py:400` calls `calc.recompute_seats_committed(trip)` after moving `BOARDED` bookings to `COMPLETED`, honouring §2.9's "always equals the sum over `CONFIRMED` or `BOARDED`" identity (which drives the value to 0 at completion) over the narrower trigger list. `test_helpers/assertions.py::assert_seat_commitment` recomputes the expectation from the same live booking set rather than pinning a literal, and no test asserts a nonzero `seats_committed` on a completed trip — so this reading is consistent with the suite and no test depends on the losing reading.

### Verification of the cardinal storage rules

`workspace/implementation/store.py` is process-local Python dicts with an explicit no-seed contract; a grep across `implementation/*.py` for `sqlite`, `open(`, `json.dump`, `pickle`, and `/tmp` returned no hits. `start.sh` installs deps only when missing and `exec`s the server in the foreground, which is what keeps the per-test-server reboot cost low enough for 8 concurrent rounds.

**Orchestrator verification**: re-read all 8 `results.N.json` independently — every round `{passed: 97, failed: 0, errors: 0, total: 97}`. Also grepped `implementation/*.py` for design-index worked-example literals (3807, 3806, 2960, 4120, 1760, 5400, 4600, 92000, 300000) — zero hits, so the clean first sweep reflects correct formula implementation rather than a design-index leak.

## Step 8: Finalize PRD — 2026-08-24T16:39:10.000Z

**SKIPPED.** Step 7 exited on the first 8-round sweep with 0 iterations beyond baseline: 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes. Per the skip condition, `PRD.md` already determined every behavior the implementation exhibits at the sites Step 7 would have targeted, so no `PRD_FINALIZED.md` is produced. Step 9 runs from `PRD.md` directly.

## Step 9: Complete PRD — 2026-08-24T16:45:50.000Z

Done. `PRD_COMPLETED.md` is written.

## Result

- **Source**: `workspace/PRD.md` — 370 lines, 75,969 chars
- **Output**: `workspace/PRD_COMPLETED.md` — 370 lines, 80,450 chars (**+4,481 chars**, 17 lines revised, no lines added/removed, no new sections)
- **Integrity verified**: §4 still holds all **37** endpoint rows; §5 still holds all **44** error rows; all 24 section headers byte-identical to source.
- **Counts**: 18 changes — **10 ambiguity-pins**, **8 mismatch-revisions**.

## Changes

- §2.5 — revise — mismatch — `current_utc` / clock instants: pinned truncation to whole seconds and the no-fractional-digits ISO rendering also used for `actual_departure_utc` / `actual_arrival_utc` — `store.py:28,76`, `routes_days.py:186`, `routes_trips.py:357`
- §2.5 — revise — mismatch — PRD claimed pass-expiry is re-evaluated "on the next read"; impl stores `RidePass.status` and compares `valid_until` only at the confirm gate, so a lapsed pass still reads `ACTIVE` — `routes_bookings.py:279`
- §2.8 rung 4 — revise — ambiguity — an absent/null/non-string body FK is unresolvable and falls to rung 6; also dropped "stop creation" (its `dock_id` comes from the path, rung 3) — `validation.py:170`, `routes_trips.py:18`
- §2.8 rung 10 — revise — mismatch — **(a)** `ERR_PASS_NOT_ACTIVE` at this rung governs pass refund only (confirm checks it below rung 22); `ERR_BOOKING_NOT_CONFIRMED` is raised below rung 12, above rung 25 — `routes_bookings.py:295`, `routes_trips.py:275`
- §2.8 rung 22 — revise — mismatch — **(a)** pinned the tendered pass's `ACTIVE` check directly below zone coverage and above rung 25 — `routes_bookings.py:286-296`
- §2.9 — revise — ambiguity — **(b)** `seats_committed` is also recomputed at boarding (unchanged) and at completion (falls to 0) — `routes_trips.py:288,400`
- §3.1 — revise — ambiguity — `LAID_UP` requires **both** layup dates non-null; one date alone reads `IN_SERVICE` — `calc.py:135`
- §3.1 — revise — ambiguity — `charted_depth_m` is reporting-only; no calculation or gate reads it (clearance uses `low_water_m` alone) — `calc.py:150`
- §3.1 — revise — ambiguity — inspection listing ties broken by `created_at` descending — `routes_estate.py:187`
- §3.2 — revise — mismatch — **(c)** Cascade A fires on any PATCH whose *recomputed* posture is `SUSPENDED`, including `SUSPENDED -> SUSPENDED`, not only on the transition edges (also corrected the cross-ref §3.7 -> §3.9) — `routes_days.py:87-88`
- §3.4 — revise — mismatch — reservation check order is rung 11 -> 19 -> 21, so off-route + berth-blocked yields `ERR_DOCK_BERTH_CONFLICT`; plus (ambiguity) the trip's `operational_status` is never tested — `routes_trips.py:179-199`
- §3.6 — revise — mismatch — **(a)** confirm pass order rewritten to expired -> zone -> status -> **capacity** -> rides (was zone -> expired -> status -> rides -> capacity) — `routes_bookings.py:277-307`
- §3.7 — revise — ambiguity — boarding manifest is inspected only after the state and suspension gates, in two sweeps (all ids resolved first), so unknown-id + non-`CONFIRMED` yields `ERR_BOOKING_NOT_FOUND` — `routes_trips.py:259-277`
- §3.7 — revise — mismatch — completion tests the clock (rung 7) **before** state; the test is skipped when `actual_departure_utc` is null — `routes_trips.py:376-382`
- §3.7 — revise — ambiguity — **(b)** completion recomputes `seats_committed` to 0 after `BOARDED -> COMPLETED` — `routes_trips.py:400`
- §3.8 — revise — ambiguity — cap-flip pre-lock bumps `version` only on slots it actually rewrites; already-locked slots untouched — `cascades.py:99-104`
- §3.9 — revise — ambiguity — Cascade A touches only docks that actually gave a provisional amount back — `cascades.py:134-144`
- §3.9 — revise — mismatch — claim approval does **not** additionally test the owning interruption's status — `routes_claims.py:60-69`

Note on target (a): the implementation adjudicated the §2.8/§3.6 contradiction by following the **§2.8 rung numbering** for expired-before-zone (rung 20 < 22) and capacity-before-rides (25 < 26), but placing `ERR_PASS_NOT_ACTIVE` **below** zone coverage rather than at rung 10 — i.e. it matches neither passage verbatim. Both passages were revised to that single order.

**Orchestrator verification**: independently confirmed 370 lines / 80,450 chars, 37 endpoint rows in §4, 44 error rows in §5, and 34 diff lines vs `PRD.md` (17 revised line-pairs, zero insertions or deletions). `implementation/` was not modified by Step 9, so the 8-round green sweep from Step 7 remains valid.
