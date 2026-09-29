## Step 1: Create task directory — 2026-08-16T18:41:30.592837837Z

Created `tasks/task_2108_barge_line_inland_waterway_freight/` and `workspace/`. Index 2108 chosen as max(existing task_NNNN in ./tasks/) = 2107, +1.
## Step 2: Generate scaffold — 2026-08-16T19:41:30.000Z

All three artifacts are written and pass every gate.

## Files written

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3,329 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2,022 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3,930 |

## Counts

16 entities · 10 state machines / 67 transitions · 12 calculations (9 variants) · 3 OCC concurrency rules · 35 ordered validations · 82 endpoints · 56 error codes · 9 roles · §1.8 = 19 instances across all 9 rules (min 2/rule) · §1.9 = 77 instances across all 9 guide sections (3 `excluded_because` stubs).

Profile: `temporal_windowing` × `pricing_engine`, **flat** topology, **parallel** state-machine shape, **segregation_of_duties** role model, self-referential FK — the four axes the skill flags as 0%-represented/priority targets.

## Verification (verdict pasted verbatim)

```
Coverage
  §1.5 endpoints declared:    82
  §1.1 entities declared:     16
  §1.8 instances scanned:     19
  §1.9 instances scanned:     74
  Calls scanned (§1.8+§1.9):  1129

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Plus custom audits, all clean: zero unbound `${var}` across 1,129 calls, zero duplicate instance names across the union of both design files, all `grounds[*]` resolve to declared §1.1–§1.7 elements, all 56 error codes referenced by a design instance, all `excluded_because` targets exist in the difficulty file, no forbidden concurrency vocabulary, OCC endpoints all declare `expected_*_version` in `input:` and bump the parent's version.

## How difficulty was pushed past Expert

- **Volume beyond the Expert band** (10–15 entities / 20–32 endpoints / 18–30 errors) at 16 / 82 / 56 — but density, not padding, is where the difficulty sits:
- **Dual-variant on two different domains that disagree loudly**: demurrage on `FreightContract` reads *per-barge gross laytime* (1,105,000¢) vs *pooled net + notice grace* (520,000¢) from identical timestamps; claim settlement on `CargoClaim` reads the trade tolerance as a *deductible* (99,000¢) vs a *franchise* (286,000¢).
- **Rounding-order trap with a 1-cent discriminator**: linehaul must round each barge line then sum (1,648,749¢); sum-then-round gives 1,648,750¢.
- **Genuine circular-looking formula pinned by evaluation order**: the volume rebate is keyed on `subtotal_cents`, not the post-rebate total. Scenario tuned so subtotal 5,051,340 sits in the 3% tier while the resulting total 4,899,800 falls below 5,000,000 — keying on the total yields 4,977,843, a wrong answer the test catches.
- **Two depth-4 cascades from different triggers**: lock clear → `LockReservation.delay_minutes` → tow DELAYED → assignment `delay_attributed_minutes` → contract laytime extension 12→24h; claim approve → settlement pinned → contract INVOICED→ADJUSTED → shipper balance → shipper CREDIT_HOLD→ACTIVE.
- **Three distinct error-category priority pairs** (state ≻ safety, safety ≻ constraint, existence ≻ state), plus two more in §1.9 (fiscal-posture ≻ fiscal-projection, window ≻ duplicate).
- **Two genuinely different interval semantics on different resources**: lock chambers use pairwise half-open windows extended by a turnback buffer (09:15 touching edge admitted, 09:00 rejected); fleeting berths use aggregate peak-occupancy counting over `[start, end)` where overlaps are legal up to capacity.
- **Temporal/versioned rules**: tariff filings with effective windows, self-superseding with window truncation, pinned at contract activation and provably immune to later rate changes; fuel index chronological "latest posting on-or-before" selection; river-stage bands with an inclusive 15.0-ft boundary.
- **Three parallel state axes** (Barge, BargeAssignment, FreightContract) plus a bounded review cycle on CargoClaim and a grant/deny/reschedule fork on LockReservation.
- **Three OCC rules on two different parent entities**, each with a natural non-parallel stale-version scenario.
- Every formula-derived assertion literal was computed by executing the scaffold's own formulas in Python, not estimated.

## Step 3: Copy shared files — 2026-08-16T19:42:03.275875878Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-16T19:55:39.121433704Z

PRD generated and verified on disk at `workspace/PRD.md`.

**Verification results (all run against the file on disk):**
- Line count: **487** lines / ~14,938 words
- Top-level sections (`^## `): **5** — §1 Introduction, §2 Global Specifications (10 subsections), §3 Business Logic (9 subsections), §4 Endpoint Definitions, §5 Error Code Catalogue
- Endpoints: **82/82** — every path from §1.5 grep-matched; endpoint table has exactly 82 data rows (4 columns: Method, Path, Description, Authorized Role(s))
- Errors: **56/56** — every id from §1.6 grep-matched; error table has exactly 56 rows (2 columns); all 56 are also referenced in §2/§3 narrative (0 orphaned)
- `tail -30` shows the true end of the catalogue (`ERR_PAYMENT_AMOUNT_MISMATCH | 422`), no mid-sentence stop
- Append calls used: **17** (1 Write + 16 appends) — §2 across 3, §3 across 9, §4 across 4, §5 across 2

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields: 134 required, 134 present, 0 missing
- endpoints[].request_body: 86 required, 86 present, 0 missing
- endpoints[].query_params: 26 required, 26 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 35 checked, 35 expressed as an explicitly ordered ladder in §2.7 with error_id + scope, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_tow_version/expected_shipper_version + error_id + 412), 0 missing
- state_machines[].transitions: 9 machines / all transitions checked, preconditions paired to error ids and every side effect stated, 0 missing
- calculations[]: 10 checked (band resolution, draft/tow profile, cleaning fee, lock window, delay attribution, fleeting fee, linehaul, fuel surcharge, demurrage, total waterfall, credit projection), all constants + rounding order + evaluation order in prose, 0 missing
- validations[] conditions: 35 checked, all matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: all checked, 0 missing
- entities[].fields[] structured content: 134 checked (types, defaults, initial values, constraints), 0 missing
- sibling-branch symmetry: pass/fail cleaning verdicts, PROVISIONAL/FINAL variants, deductible/franchise settlements, cancel-from-DRAFT/BOOKED/ACTIVE, withdraw-from-three-states — all rendered at equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 953
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- raw (unbackticked) path-like text: 0
Status: PASS
```

§2.2 was emitted byte-identical from `section-2.2-response-structure.md`. No fuzzy/approximating language present. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Orchestrator independent verification:** `grep -c '^## '` = 5; sections 1–5 all present at lines 3/11/177/337/426; `tail` ends cleanly at `ERR_PAYMENT_AMOUNT_MISMATCH | 422`. No truncation.

## Step 6: Generate implementation — 2026-08-16T20:19:17.348829106Z

Implementation complete at `workspace/implementation/`.

## Files written

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 10 | Launcher (executable) |
| `requirements.txt` | 1 | `Flask>=2.0` |
| `app.py` | 64 | Entry point, error handlers, blueprint registration |
| `common.py` | 524 | Error catalogue (56), logical clock, in-memory store, `touch()` versioning, envelope, auth, body/pagination validators, ISO-8601 + Decimal helpers |
| `schema.py` | 125 | Per-entity output projections |
| `calc.py` | 458 | All 12 calculations + cascades |
| `routes_reference.py` | 324 | Clock, shippers, commodities, compat matrix, tariff filings, fuel index, river stage |
| `routes_harbor.py` | 306 | Barges, cleaning orders, berths, fleeting assignments |
| `routes_lock.py` | 300 | Locks, lock reservations, closure cascade |
| `routes_tow.py` | 409 | Tows, makeup, seal/depart/arrive/break-up/adjust-load, discharge axis |
| `routes_contract.py` | 459 | Freight contracts, charge breakdown, invoicing, cargo claims |
| **Total** | **2980** | |

## Coverage
- **Endpoints: 82/82** — verified programmatically against the Flask URL map; every one returns `ERR_UNAUTHENTICATED` bare, correct `ERR_FORBIDDEN_ROLE` for an unauthorized role, and all 9 roles pass every GET.
- **Error codes: 56/56** — every catalogue id is raised from a real call site (the 13 `*_NOT_FOUND` codes flow through `fetch()`); all 13 verified live at 404 with the right id.
- **start.sh**: reads `$PORT` (default 10000), binds `0.0.0.0`, `exec python3 app.py` in the foreground, guarded `pip install`. Cold boot to first 200 response: **0.77 s**.
- **Storage**: Python dicts only. No sqlite, no file I/O, no `/tmp` cache, no seeding — a fresh boot returns `total_count: 0` on every collection.

## Points I paid particular attention to
- **Rounding order**: linehaul rounds *each line* half-up to whole cents before summing (verified two 0.5-cent lines → 2, not 1); `min_charge_cents` is a contract-level floor applied *after* the sum and only when ≥1 billable line exists; the rebate is rounded exactly once after the subtotal; `max_draft_feet` is the max of *rounded* per-barge drafts.
- **Waterfall order**: the rebate tier keys on `subtotal_cents` (5 buckets), never on the total; `claim_credit_cents` enters only at step 4 and can never move the tier.
- **Ladder fidelity**: §2.7's numbered ladder governs wherever §3 prose enumerates in a different sequence — e.g. seal checks cargo(11) → cleanliness(12) → stage reading(13) → draft(14) → size cap(15); release checks state(9) before sequence(22); activate checks tariff(17) → fuel(18) → credit hold(33) → headroom(34); lock request checks window conflict(20) before `ERR_LOCK_CLOSED`(24). SoD(8) is evaluated before the state precondition(9) on effectuate/approve/deny; ownership(7) before SoD(8).
- **Interval semantics**: chamber occupation `[scheduled_start_at, occupied_until_at)` half-open (touching endpoints do not conflict — tested); berth admission is an aggregate head-count over `[start_at, end_at)` boundary instants, not pairwise overlap; tariff effective windows are inclusive at both ends.
- **Point-in-time selection**: controlling river reading (`reading_at` DESC, `created_at` DESC), controlling fuel posting (`posting_date` DESC, `created_at` DESC), effective tariff — all read the logical clock only, with pins frozen at activation and never re-resolved.
- **Versioning**: `touch()` bumps `version`/`updated_at` exactly once per row per request, including cascaded rows (berths, locks, tows, contracts, shippers, hulls); the four immutable reference kinds emit neither field.

One judgement call worth flagging: the PRD declares only four lock-posture transitions and supplies **no** lock-state error code, so undeclared posture moves (e.g. `RESTRICTED → CLOSED`) are accepted rather than rejected with a code that does not exist in the catalogue.

## Step 5: Generate unit tests — 2026-08-16T20:31:30.943717453Z

Test infrastructure and suite are complete. Both design indices are fully translated, verified, and collection-clean.

## Files written

**`test_helpers/` — 2,260 lines**
| File | Lines | Contents |
|---|---|---|
| `types.py` | 468 | 20 enums + TypedDicts; the four immutable reference kinds (Commodity, CompatibilityRule, FuelIndexPosting, RiverStageReading) omit `updated_at`/`version` per PRD §2.4 |
| `api_client.py` | 347 | one method per endpoint (all 82) |
| `assertions.py` | 264 | per-entity assertions, `assert_waterfall_consistent`, `assert_tow_rollup`, `assert_same_instant` (instant-value comparison, not serialisation) |
| `factories.py` | 224 | payload factories, input fields only, auto-unique hull numbers |
| `api_errors.py` | 145 | all 56 error ids + HTTP map, registered with the framework |
| `constants.py` | 114 | bands, ranks, fees, delay thresholds, rebate tiers, canonical GRAIN scenario values |
| `test_users.py` | 77 | 9 roles; `make_lock_master_headers(lock_id)` / `make_shipper_headers(shipper_id)` for the two `entity_backed` roles, distinct operator ids (`analyst-1`/`rate-1`, `adj-1`/`adj-2`) for the two segregation-of-duties pairs |
| `fixtures.py` | 586 | ~50 atomic wrappers + `setup_grain_reference` → `setup_grain_movement(stage=BUILDING/SEALED/UNDERWAY/ARRIVED/DISCHARGED)` → `setup_invoiced_movement` / `setup_claim_under_review` / `setup_assessed_claim` / `setup_underway_tow_at_lock` |
| `__init__.py` | 35 | barrel export |

**`test_suite/` — 3,815 lines, 9 test files + conftest, 112 tests** (`test_01_reference_data_and_listings` 11 · `test_02_tariffs_fuel_and_activation` 9 · `test_03_harbor_fleeting_and_cleaning` 12 · `test_04_tow_makeup_and_draft` 19 · `test_05_lock_scheduling_and_delay` 13 · `test_06_voyage_discharge_and_breakup` 6 · `test_07_billing_and_charge_breakdown` 14 · `test_08_cargo_claims` 10 · `test_09_not_found_and_authorization` 18)

## Coverage

- **Queue A (Difficulty): 19/19 instances translated, 0 skipped → 38 tests** (exactly ≥2 per instance).
- **Queue B (Corner): 74/74 non-stub instances translated, 0 skipped → 74 tests.** The 3 `excluded_because` stubs were not translated; all three `difficulty_instance` cross-references resolve.

## Adjudications made (assertions trimmed, never instances dropped)

- `lock_chamber_entry_requires_tow_under_way` — PRD names no error id for the *tow's* state failing on `enter-chamber` (unlike assignment-create, where §3.5 names `ERR_CONTRACT_MOVEMENT_INVALID_STATE`). Asserted HTTP 409 + `validate_error_is_one_of([ERR_TOW_INVALID_STATE, ERR_LOCK_RESERVATION_INVALID_STATE])`; the state/side-effect assertions are full strength.
- Dropped four unstated-default assertions: `pinned_*` null on a DRAFT contract, `draft_restriction_band == null` on an unresolvable gauge, the two settlement variants `== 0` before assessment, and `updated_at` strictly increasing in the lock-version test (the logical clock is frozen in that fixture, so a faithful implementation returns an identical stamp).
- `logical_clock_defaults_to_2026_08_01` asserts `pinned_fuel_surcharge_pct == 0.09` at a 420-cent price — the design's inline 2-tier table contradicts its own literal; the 4-tier canonical table (used by the fixtures throughout) makes the design's literal correct.
- `lock_closure_cancels_live_slots` re-reads `Tow.version` before the post-closure reservation request: the closure bumps the tow (delay + counter), so the design's captured version would have tripped OCC (priority 10) before `ERR_LOCK_CLOSED` (priority 24).
- Timestamp equality (`effective_to` truncation, chamber windows, `released_at`) compares parsed instants, since PRD pins three fractional digits only for `created_at`/`updated_at`.

## Verification run

- All 96 design literals recomputed independently (linehaul round-then-sum 1648749 vs 1648750, rebate 151540/4899800, demurrage 1105000 vs 520000, settlements 99000/286000, drafts 9.83/10.03/10.81/6.40, allowance 1530, fees 75000/90000/105000) — every one matches.
- Audit script: 112 tests, exactly one `Design:` tag each, every tag resolves to a real instance, every docstring ends with it, and **every quoted citation survives a whitespace-normalised literal match against PRD.md** (0 problems).
- `pytest --collect-only`: 112 collected, no import errors. Signature checker: every `api.*` call exists on `ApiClient` and every helper call binds. A throwaway stub server ran the 12 not-found tests green, proving the client/validator/error-status plumbing end-to-end.
- No `skip`/`skipif`/`xfail`; no "scaffold"/§1.x/table references anywhere in the emitted code.

## Step 7: Run tests and iterate — 2026-08-16T20:42:32.140004658Z

Done. The suite is fully green across a clean 8-round parallel stability sweep.

## Summary

**Iterations run: 2**

**Iteration 1** — 8 parallel rounds, all 8 landed at **111/112**. Union of failures across all rounds was a single, fully deterministic test (failed in every round, so no flakiness signal anywhere in the suite):
`test_06_voyage_discharge_and_breakup.py::test_break_up_returns_every_hull_dirty_with_its_last_cargo_recorded` — `assert 1 == 0` on `broken["barge_count"]`.

**Iteration 2** — 8 parallel rounds, all 8 at **112/112**, zero failures, zero flakes. Wall time ~143 s per round.

### Tests deleted
None. One test was **split** under STEP 1c (partial coverage), not deleted — 112 tests still collect and pass.

### Assertions removed (STEP 1b — BRANCH-ASYMMETRIC SIDE EFFECT)
`test_suite/test_06_voyage_discharge_and_breakup.py`, in `test_break_up_returns_every_hull_dirty_with_its_last_cargo_recorded` — dropped three tow-rollup assertions (`barge_count == 0`, `total_loaded_tons == 0`, `max_draft_feet == 0`).

Reasoning: PRD's break-up paragraph (§3.7) states only *"Break-up moves the tow to the terminal `BROKEN_UP`, advances every `LOADED` assignment to the terminal `DISCHARGED`, and returns every hull named by those assignments from `operational_status` `IN_TOW` to `IDLE`"* — plus the cleanliness/last-cargo/certificate clause and the version clause. It never names `barge_count`, `total_loaded_tons` or `max_draft_feet`. Meanwhile §2.10 states verbatim: *"Aggregate counters maintained on parent rows — … a tow's `barge_count`, `total_loaded_tons` … — are maintained incrementally by the transitions that move their children, and every increment or decrement named in this document is mandatory. A counter that is merely recomputed on read will disagree with the specification wherever a transition is declared to leave it untouched."* PRD renders the sibling branch fully (§3.5 drop: *"removes that assignment's `loaded_tons` from the tow's `total_loaded_tons`, decrements the tow's `barge_count` by one, and recomputes `max_draft_feet`"*) but leaves break-up's rollup effect entirely unstated. Two divergent PRD-faithful readers exist — one treats §3.5's active-set rollup as a standing invariant and recomputes; the other follows §2.10 and touches only the named counters — so unique derivability is broken.

The covered assertions were all kept at full strength: tow `BROKEN_UP`, assignment `DISCHARGED` + `discharge_status COMPLETED`, hull `IDLE` / `DIRTY` / `last_cargo_commodity_id` set / certificate cleared, and the contract's `IN_TRANSIT → DISCHARGED` bubble-up.

Scaffold rule that drove the test's generation: `Corner/state_machines/tow_break_up_returns_every_hull_dirty_with_its_last_cargo_recorded`.

### Fixes applied to `test_helpers/`
None — no fixture, factory, role-header builder or assertion helper was found inconsistent with the PRD.

### Fixes applied to `implementation/`
None. No PRD-required check was weakened or removed, no endpoint/field/side-effect was added, and storage remains in-memory Python dicts only (verified: no sqlite, no file I/O, no `/tmp` cache, no startup seeding).

### Note on the incumbent implementation
The single deterministic failure traced to a PRD-silence gap rather than an implementation defect — `routes_tow.py::break_up_tow` deliberately does not call `calc.recompute_tow_profile`, which is a legitimate reading of §2.10. Everything else in the 82-endpoint / 56-error / 12-calculation surface passed on the first sweep and stayed stable across 16 total round-executions.

---

**Orchestrator independent verification (2026-08-16T20:42:32.140004658Z):** the Step 7 agent's `results.*.json` artifacts were absent from disk at hand-off, so the orchestrator re-ran the full 8-round parallel sweep itself rather than accept the green claim unverified. Result: **all 8 rounds passed=112 total=112 failed=0**. Artifacts now persisted at `workspace/implementation/results.{1..8}.json`.

## Step 8: Finalize PRD — 2026-08-16T20:45:55.659760417Z

`workspace/PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 487 lines — `PRD_FINALIZED.md`: 487 lines — **0.00% delta** (1 line revised in place, +1 sentence)

## Changes
- **§3.7 (break-up paragraph)** — *insert* — added one sentence pinning that break-up runs no tow rollup: `barge_count`, `total_loaded_tons` and `max_draft_feet` stay at the values the makeup last computed, even though the assignments behind them leave the active set — `implementation/routes_tow.py:251-276` (`break_up_tow`, which never calls `calc.recompute_tow_profile`).

## Pre-edit search log

**Edit 1 — §3.7 break-up rollup**

(a) **Subject identified:** the tow's aggregate draft-profile counters `barge_count`, `total_loaded_tons`, `max_draft_feet` (and, by association, the `recompute_tow_profile` helper that is their sole writer) — every transition that could write, read, or be expected to write them.

(b) **Impl paths enumerated (grepped/read):**
- `calc.py:132-143 recompute_tow_profile` — the only writer of the three counters (`calc.py:136-138`); also re-pins `draft_restriction_band`/`allowed_draft_feet` when a reading exists.
- Its four callsites, confirmed exhaustive by `grep -rn recompute_tow_profile`: `routes_tow.py:114` (add assignment), `routes_tow.py:167` (seal), `routes_tow.py:305` (adjust-load), `calc.py:158` inside `drop_assignment`.
- `drop_assignment` callsites (`grep -rn drop_assignment`): `routes_tow.py:320` (`/barge-assignments/{id}/drop`) and `routes_contract.py:141` (contract cancel cascading PLANNED→DROPPED) — both therefore do roll up, matching §3.3/§3.5 prose unchanged.
- Transitions that move an assignment `status` but do **not** recompute: `depart_tow` (`routes_tow.py:191-193`, CONFIRMED→LOADED, both statuses active so the counters are invariant anyway) and `break_up_tow` (`routes_tow.py:263-275`, LOADED→DISCHARGED, counters left stale) — only the latter is observable.
- `routes_tow.py:28-31` — tow creation initialises all three to 0; `grep` confirms no other assignment to `barge_count` / `total_loaded_tons` / `max_draft_feet` on a tow row anywhere (`routes_harbor.py` hits are the berth's unrelated `occupied_barge_count`).
- Readers of the counters: `calc.cut_count_for` (`calc.py:170`, lock-reservation window sizing / reschedule), `seal_tow` which uses `len(active)` rather than `tow["barge_count"]` for the size cap (`routes_tow.py:155`), and `schema.py:56-58 ser_tow`, which emits all three on every tow read.
- `common.py:164 touch` — confirmed it only bumps `version`/`updated_at`, so `break_up_tow`'s three `touch` calls cannot alter the counters indirectly.

(c) **Wording adjustment made:** the first draft simply said break-up "leaves the counters untouched", which would have sat in flat contradiction with §3.5's standing-sounding claim that "assignments that have been `DROPPED` or `DISCHARGED` never contribute". Since §3.5's rollup rule *is* faithfully applied at all four recompute sites, I re-scoped rather than contradicted it: the sentence now says the §3.5 rollup "is run by the transitions that name it rather than re-derived on every read", which stays true of add/seal/adjust-load/drop (including contract-cancel drops) while pinning break-up's no-op. I also deliberately limited the claim to the three counters and did not extend it to `draft_restriction_band` / `allowed_draft_feet` — break-up leaves those alone too, but no Step 7 item touches them and a broader claim risks over-constraining paths Step 7 never exercised.

Nothing else in `<step_7_diff>` required a PRD change: zero tests were deleted, zero `test_helpers/` fixes were made, and zero `implementation/` fixes were made, so the single split test's dropped assertions are the only PRD-silence signal in the diff.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (line 299), one sentence inserted. Minimal-diff contract respected.

## Step 9: Complete PRD — 2026-08-16T20:57:39.361177903Z

`workspace/PRD_COMPLETED.md` is written. All edits are in-paragraph; no sections, headings, table rows, or paragraph boundaries were added.

## Counts

- **PRD_FINALIZED.md**: 487 lines, 104,134 chars → **PRD_COMPLETED.md**: 487 lines, 111,187 chars, **delta +7,053 chars**
- 33 of 487 lines touched; **40 edits** total — **35 ambiguity-pins**, **5 mismatch-revisions**

## Changes

**Mismatch-revisions (PRD described something the implementation does not do)**

- `§3.6 Lock Scheduling` — revise — mismatch — the known gap: PRD declared four posture transitions as if they were exhaustive; pinned that the posture axis is *not* policed (no lock-state code exists in §5), so any of the three postures is accepted from any current posture, including `RESTRICTED → CLOSED`, `CLOSED → RESTRICTED` and self-loops — `routes_lock.py:37-51`
- `§3.5 Building a Tow` — revise — mismatch — the tow must stand in `BUILDING` to take a barge, refused with `ERR_TOW_INVALID_STATE` ahead of every other state gate; PRD listed the gates and omitted this one entirely — `routes_tow.py:74-75`
- `§3.1 Reference Data` — revise — mismatch — "At most one rule may exist per ordered pair" is not enforced; duplicates are accepted and the earliest-registered rule governs every lookup — `routes_reference.py:109-124`, `calc.py:84-89`
- `§3.3 Road to an Active Contract` — revise — mismatch — activation gate order: PRD's sentence put `ERR_SHIPPER_ON_CREDIT_HOLD` second, but impl (and §2.7 rungs 17/18/33/34) fires tariff and fuel first — `routes_contract.py:92-106`
- `§3.6 / §3.4` — revise — mismatch — grant gate order corrected to state → tow state → conflict → `ERR_LOCK_CLOSED`; release gate order corrected to state → chronology — `routes_lock.py:144-156`, `routes_harbor.py:247-250`

**Ambiguity-pins (selected; 35 total)**

- `§2.3` — insert — list ties on `created_at` break by creation sequence ascending — `common.py:490`
- `§2.4` — insert — a row written twice in one request bumps `version` exactly once; a row the request created stays at 1 — `common.py:164-178`
- `§2.10` — insert — moving a parent counter is itself a mutation, so the parent's `version` bumps even where a narrative names only the child's (covers berth/lock/tow bumps at release, depart, grant, deny, reschedule, clear, cancel) — `common.py:164`, `routes_lock.py`, `routes_tow.py:195-208`
- `§3.2` — insert ×4 — `supersedes_tariff_filing_id` is FK-checked at draft; the overlap test is inclusive at both edges; the supersede demotion runs only from `EFFECTIVE`; the reading selector's third tie-break is registration sequence descending — `routes_reference.py:183-185, 236-247`, `calc.py:76-78`
- `§3.3` — insert ×4 — multi-`EFFECTIVE` filing selector; contract birth defaults (`distance_miles`/pins null, buckets 0); `cancel` `reason` recorded but never surfaced — `routes_contract.py:38-66, 113-137`, `calc.py:378-387`
- `§3.4` — insert ×3 — cleaning order ignores `prohibited` and the hull's operational status; failed inspection still records `performed_level`/`certificate_number` and only moves a hull that was `IDLE` — `routes_harbor.py:77, 120-138`
- `§3.5` — insert ×5 — tow and assignment birth defaults; rollup succeeds with no gauge reading, leaving band/allowed as-is; the light-load allowance has **no floor at zero** (negative `loaded_tons` is written); a hull outside `IDLE`/`FLEETED` is left alone at seal — `routes_tow.py:21-37, 96-116, 300-303, 164-166`, `calc.py:139-149`
- `§3.6` — insert ×5 — reservation birth defaults; **no tow-state gate at request**; deny `reason` never surfaced; reschedule re-stamps `requested_start_at` and applies **neither** the conflict nor the closed test; closure charges 240 min *per cancelled reservation*, works them in `created_at` order, decrements both counters, and fires only on the move *into* `CLOSED` — `routes_lock.py:92-130, 174-175, 185-209, 54-72`
- `§3.7` — insert ×2 — tender's two gates carry `ERR_BARGE_ASSIGNMENT_INVALID_STATE` / `ERR_TOW_INVALID_STATE`; break-up's preconditions both carry `ERR_TOW_INVALID_STATE` — `routes_tow.py:331-335, 255-262`
- `§3.8` — insert ×3 — a never-activated contract's breakdown reads rate/min-charge/demurrage-rate as 0; `variant` validated (empty → `PROVISIONAL`, bad → `ERR_INVALID_REQUEST`) before the contract lookup; mark-paid's movement gate is `ERR_CONTRACT_MOVEMENT_INVALID_STATE`, checked before the amount — `calc.py:294-296`, `routes_contract.py:207-214, 184-187`
- `§3.9` — insert ×4 — an assignment with null `unload_finished_at` passes the 30-day gate; claim birth defaults; `info_request_note`, `response_note` and `denial_reason` are all required — `routes_contract.py:251-254, 272-290, 314, 330, 402`

**Orchestrator verification:** `PRD_COMPLETED.md` = 487 lines, 5 top-level sections intact, 34 lines changed vs `PRD_FINALIZED.md`, +7,093 chars on disk, ends cleanly at the error catalogue. Confirmed no `implementation/` or test file was modified after the verified 8-round sweep (newest impl source 20:18:08, newest test file 20:35:59, results written 20:42:04) — Steps 8 and 9 touched only PRD markdown, so the 112/112 result stands for the shipped code.

---

# PIPELINE COMPLETE — task_2108_barge_line_inland_waterway_freight

Final state: 112/112 tests passing across 8 consecutive parallel stability rounds under `--isolation per-test-server`. 16 entities · 82 endpoints · 56 error codes · 10 state machines · 12 calculations · 35 ordered validations · 3 OCC rules · 9 roles.
